import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from scripts.token_usage import (
    Msg,
    agent_id_from_name,
    agent_role,
    dedupe,
    parse_file,
    slug_for,
    slugify,
)

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "token_usage.py"
PROJECTS = REPO / "tests" / "fixtures" / "token_usage" / "projects"
DEMO_SLUG = PROJECTS / "-Users-example-demo-repo"
ROOT_SID = "11111111-1111-4111-8111-111111111111"
COPY_SID = "33333333-3333-4333-8333-333333333333"
OTHER_SID = "55555555-5555-4555-8555-555555555555"
ROOT_FILE = DEMO_SLUG / f"{ROOT_SID}.jsonl"
AAA_FILE = DEMO_SLUG / ROOT_SID / "subagents" / "agent-aaa111.jsonl"


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--projects-dir", str(PROJECTS), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
    )


def run_json(*args):
    result = run_cli(*args, "--format", "json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_script(*args, env=None):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO,
        env=env,
    )


def msg(mid, model="m", output=1, ts="2026-01-01T00:00:00.000Z"):
    return Msg(
        mid=mid,
        model=model,
        effort=None,
        input=0,
        cache_write=0,
        cache_read=0,
        output=output,
        sidechain=False,
        agent_id=None,
        attribution=None,
        ts=ts,
    )


def assistant_line(sid, cwd, mid, output, ts="2026-09-09T12:00:00.000Z", sidechain=False, agent_id=None):
    obj = {
        "type": "assistant",
        "timestamp": ts,
        "sessionId": sid,
        "cwd": cwd,
        "version": "0.0.0-test",
        "isSidechain": sidechain,
        "effort": "high",
        "uuid": f"u-{mid}-{output}",
        "message": {
            "id": mid,
            "model": "claude-opus-5-5",
            "role": "assistant",
            "usage": {
                "input_tokens": 1,
                "cache_creation_input_tokens": 2,
                "cache_read_input_tokens": 3,
                "output_tokens": output,
            },
        },
    }
    if agent_id:
        obj["agentId"] = agent_id
    return json.dumps(obj)


def write_session(directory, sid, cwd, lines=None):
    """Write <directory>/<sid>.jsonl with a user line plus the given assistant lines."""
    directory.mkdir(parents=True, exist_ok=True)
    head = json.dumps(
        {
            "type": "user",
            "timestamp": "2026-09-09T11:59:00.000Z",
            "sessionId": sid,
            "cwd": cwd,
            "version": "0.0.0-test",
            "isSidechain": False,
            "uuid": f"user-{sid}",
            "message": {"role": "user", "content": "placeholder prompt"},
        }
    )
    body = [head, *(lines or [])]
    (directory / f"{sid}.jsonl").write_text("\n".join(body) + "\n", encoding="utf-8")


class ParsingTests(unittest.TestCase):
    def test_agent_id_from_file_name(self):
        self.assertEqual(agent_id_from_name("agent-aaa111.jsonl"), "aaa111")
        self.assertEqual(agent_id_from_name("workflow-agent-xyz9.jsonl"), "xyz9")

    def test_role_comes_from_meta_file(self):
        info = parse_file(AAA_FILE)
        self.assertEqual(agent_role(AAA_FILE, info), "Explore")

    def test_role_falls_back_to_subagent_without_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agent-nometa.jsonl"
            path.write_text(
                json.dumps(
                    {
                        "type": "assistant",
                        "timestamp": "2026-01-01T00:00:00.000Z",
                        "message": {
                            "id": "msg_x",
                            "model": "claude-haiku-5-5",
                            "usage": {"input_tokens": 1, "output_tokens": 1},
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(agent_role(path, parse_file(path)), "subagent")

    def test_dedupe_keeps_last_line_per_message_id(self):
        kept = dedupe([msg("msg_1", output=4), msg("msg_2", output=9), msg("msg_1", output=8)])
        self.assertEqual({m.mid: m.output for m in kept}, {"msg_1": 8, "msg_2": 9})

    def test_parse_skips_malformed_and_synthetic_lines(self):
        info = parse_file(ROOT_FILE)
        ids = [m.mid for m in info.msgs]
        self.assertNotIn("msg_synthetic_1", ids)
        self.assertNotIn("msg_broken", ids)
        self.assertEqual(ids.count("msg_root_1"), 2)  # raw lines; dedupe happens later

    def test_slugify_matches_directory_name(self):
        slug = slugify("/Users/example/demo-repo")
        self.assertRegex(slug, r"^[A-Za-z0-9-]+$")
        self.assertTrue(slug.endswith("Users-example-demo-repo"), slug)
        self.assertEqual(slug, slug_for(Path("/Users/example/demo-repo").resolve()))

    def test_long_slug_is_cut_and_hashed_like_claude_code(self):
        path = Path("/" + "a" * 249)
        slug = slug_for(path)
        self.assertEqual(slug[:200], "-" + "a" * 199)
        self.assertRegex(slug[200:], r"^-[0-9a-z]+$")
        if os.name == "posix":
            # Value produced by Claude Code's own sanitizer for this exact path.
            self.assertEqual(slug, "-" + "a" * 199 + "-wkpu26")


class CliTests(unittest.TestCase):
    def test_latest_skips_newer_session_without_subagents(self):
        result = run_cli("--latest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"### Session `{ROOT_SID[:8]}`", result.stdout)
        self.assertNotIn(COPY_SID[:8], result.stdout.split("\n", 1)[0])

    def test_roles_and_models_in_json(self):
        report = run_json("--session", ROOT_SID)
        roles = {t["role"]: t for t in report["threads"]}
        self.assertEqual(set(roles), {"root", "Explore", "general-purpose"})
        self.assertEqual(list(roles["Explore"]["per_model"]), ["claude-haiku-5-5"])
        self.assertEqual(roles["Explore"]["per_model"]["claude-haiku-5-5"]["effort"], "high")
        self.assertEqual(roles["general-purpose"]["per_model"]["claude-opus-5-5"]["effort"], "xhigh")

    def test_totals_dedupe_and_skip_mirror(self):
        report = run_json("--session", ROOT_SID)
        totals = report["totals"]
        self.assertEqual(totals["threads"], 3)
        self.assertEqual(totals["responses"], 6)
        self.assertEqual(totals["input_tokens"], 48)
        self.assertEqual(totals["cache_creation_input_tokens"], 180)
        self.assertEqual(totals["cache_read_input_tokens"], 4800)
        self.assertEqual(totals["output_tokens"], 200)
        self.assertEqual(totals["total_tokens"], 5228)
        self.assertEqual(report["cache_hit_rate_on_input"], 95.5)
        self.assertEqual(report["per_model"]["claude-opus-5-5"]["total_tokens"], 4047)
        self.assertEqual(report["per_model"]["claude-opus-5-5"]["threads"], 2)
        self.assertEqual(report["per_model"]["claude-haiku-5-5"]["total_tokens"], 1181)
        self.assertEqual(report["wall_seconds"], 150)

    def test_resumed_copy_is_not_counted_twice(self):
        report = run_json("--session", COPY_SID)
        self.assertEqual(report["totals"]["responses"], 1)
        self.assertEqual(report["totals"]["total_tokens"], 103)

    def test_unmatched_sidechain_mirror_is_counted_once(self):
        # Sidechain lines for a workflow subagent whose agent file is missing.
        # They must surface as one subagent thread, deduplicated by message id.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = Path(tmp) / "repo"
            sid = "aaaaaaaa-0000-4000-8000-000000000001"
            cwd = str(project.resolve())
            write_session(
                projects / slug_for(project.resolve()),
                sid,
                cwd,
                [
                    assistant_line(sid, cwd, "m-root", 10, ts="2026-09-09T12:00:00.000Z"),
                    assistant_line(sid, cwd, "m-g1", 5, ts="2026-09-09T12:00:10.000Z", sidechain=True, agent_id="ghost"),
                    assistant_line(sid, cwd, "m-g1", 7, ts="2026-09-09T12:00:11.000Z", sidechain=True, agent_id="ghost"),
                    assistant_line(sid, cwd, "m-g2", 4, ts="2026-09-09T12:00:20.000Z", sidechain=True, agent_id="ghost"),
                ],
            )
            result = run_script("--projects-dir", str(projects), "--session", sid, "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            threads = {t["id"]: t for t in report["threads"]}
            self.assertEqual(set(threads), {sid, "ghost"})
            self.assertEqual(threads["ghost"]["role"], "subagent")
            self.assertEqual(threads[sid]["per_model"]["claude-opus-5-5"]["output_tokens"], 10)
            self.assertEqual(threads["ghost"]["per_model"]["claude-opus-5-5"]["responses"], 2)
            self.assertEqual(threads["ghost"]["per_model"]["claude-opus-5-5"]["output_tokens"], 11)
            self.assertEqual(report["totals"]["responses"], 3)
            self.assertEqual(report["totals"]["output_tokens"], 21)

    def test_markdown_table_and_hit_rate(self):
        result = run_cli("--session", ROOT_SID)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("| Thread | Role | Model / effort |", result.stdout)
        self.assertIn("| `aaa111` | Explore | claude-haiku-5-5 / high | 2 |", result.stdout)
        self.assertIn("| **all** | 3 | 6 | 48 | 180 | 4,800 | 200 | 5,228 |", result.stdout)
        self.assertIn("Cache hit rate on input: 95.5%", result.stdout)

    def test_list_row_shows_subagent_count(self):
        result = run_cli("--list", "--limit", "20")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, rf"{ROOT_SID[:8]}\s+2\s+/Users/example/demo-repo")

    def test_list_limit(self):
        result = run_cli("--list", "--limit", "1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(result.stdout.strip().splitlines()), 2)  # header + one row

    def test_project_filter_by_slug_excludes_other_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            mine, other = Path(tmp) / "mine", Path(tmp) / "other"
            mine_sid = "bbbbbb01-0000-4000-8000-000000000001"
            other_sid = "bbbbbb02-0000-4000-8000-000000000002"
            write_session(projects / slug_for(mine.resolve()), mine_sid, str(mine.resolve()))
            write_session(projects / slug_for(other.resolve()), other_sid, str(other.resolve()))
            result = run_script("--projects-dir", str(projects), "--list", "--project", str(mine))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(mine_sid[:8], result.stdout)
            self.assertNotIn(other_sid[:8], result.stdout)

    def test_project_filter_matches_recorded_cwd_in_other_directory(self):
        # Remote sessions live in ssh-* directories whose names are not the slug.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            project = Path(tmp) / "work" / "repo"
            by_cwd = "cccccc01-0000-4000-8000-000000000001"
            by_slug = "cccccc02-0000-4000-8000-000000000002"
            unrelated = "cccccc03-0000-4000-8000-000000000003"
            write_session(projects / "ssh-7edcde87-remote", by_cwd, str(project.resolve()))
            write_session(projects / slug_for(project.resolve()), by_slug, str(Path(tmp) / "elsewhere"))
            write_session(projects / "ssh-other-host", unrelated, str(Path(tmp) / "elsewhere"))
            result = run_script("--projects-dir", str(projects), "--list", "--project", str(project))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(by_cwd[:8], result.stdout)
            self.assertIn(by_slug[:8], result.stdout)
            self.assertNotIn(unrelated[:8], result.stdout)

    def test_claude_config_dir_selects_default_projects_dir(self):
        with tempfile.TemporaryDirectory() as config, tempfile.TemporaryDirectory() as home:
            sid = "dddddd01-0000-4000-8000-000000000001"
            write_session(Path(config) / "projects" / "-some-project", sid, "/some/project")
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
            env.update(HOME=home, USERPROFILE=home, CLAUDE_CONFIG_DIR=config)
            result = run_script("--list", env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(sid[:8], result.stdout)

            # Without the variable the default is ~/.claude/projects.
            home_sid = "dddddd02-0000-4000-8000-000000000002"
            write_session(Path(home) / ".claude" / "projects" / "-home-project", home_sid, "/home/project")
            env.pop("CLAUDE_CONFIG_DIR")
            result = run_script("--list", env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(home_sid[:8], result.stdout)
            self.assertNotIn(sid[:8], result.stdout)

    def test_list_stays_fast_with_many_sessions(self):
        # Regression: discovery used to glob the whole project directory once per
        # session, and --list parsed every transcript. 2000 sessions took ~15 s.
        with tempfile.TemporaryDirectory() as tmp:
            projects = Path(tmp) / "projects"
            directory = projects / "-Users-example-big-repo"
            directory.mkdir(parents=True)
            for i in range(2000):
                sid = f"{i + 1:08x}-0000-4000-8000-000000000000"
                line = json.dumps(
                    {
                        "type": "user",
                        "timestamp": f"2026-10-{1 + i % 28:02d}T08:00:00.000Z",
                        "sessionId": sid,
                        "cwd": "/Users/example/big-repo",
                        "message": {"role": "user", "content": "x"},
                    }
                )
                (directory / f"{sid}.jsonl").write_text(line + "\n", encoding="utf-8")
            started = time.monotonic()
            result = run_script("--projects-dir", str(projects), "--list", "--limit", "1")
            elapsed = time.monotonic() - started
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(len(result.stdout.strip().splitlines()), 2)
            self.assertLess(elapsed, 3.0, f"--list --limit 1 took {elapsed:.2f}s")

    def test_date_filter_uses_local_start_date(self):
        local = datetime.fromisoformat("2026-09-09T12:00:00+00:00").astimezone().strftime("%Y-%m-%d")
        result = run_cli("--list", "--date", local)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(ROOT_SID[:8], result.stdout)

    def test_date_with_no_sessions_exits_1(self):
        result = run_cli("--list", "--date", "1999-01-01")
        self.assertEqual(result.returncode, 1)

    def test_ambiguous_session_prefix_exits_2(self):
        result = run_cli("--session", "1111")
        self.assertEqual(result.returncode, 2)
        self.assertIn("matches", result.stderr)

    def test_unique_session_prefix_resolves(self):
        result = run_cli("--session", "11111")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f"### Session `{ROOT_SID[:8]}`", result.stdout)

    def test_bad_date_exits_2(self):
        for bad in ("2026-13-40", "09/09/2026", "yesterday"):
            with self.subTest(date=bad):
                result = run_cli("--list", "--date", bad)
                self.assertEqual(result.returncode, 2)
                self.assertIn("invalid --date", result.stderr)

    def test_no_mode_exits_2(self):
        self.assertEqual(run_cli().returncode, 2)

    def test_missing_projects_dir_exits_2(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--projects-dir", str(REPO / "does-not-exist"), "--list"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
