"""Checks for the generated profiles/ tree, the root CLAUDE.md and the build script.

Expectations below are written out from the contract table, not read from
scripts/build_profiles.py, so a wrong PROFILES row fails here.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO / "profiles"
BUILD_SCRIPT = REPO / "scripts" / "build_profiles.py"
CLAUDE_MD = REPO / "CLAUDE.md"

sys.path.insert(0, str(REPO / "scripts"))
import build_profiles  # noqa: E402

ROLES = ("explorer", "worker", "tester", "reviewer", "researcher")
HAIKU = "claude-haiku-5-5"
SONNET = "claude-sonnet-5-5"
OPUS = "claude-opus-5-5"
FABLE = "claude-fable-5-1"
ALLOWED_SETTINGS_EFFORT = {"low", "medium", "high", "xhigh"}

# The contract table, written out from the spec rather than read from scripts/build_profiles.py,
# so a wrong PROFILES row fails here. Per profile: root (model, effort), the default subagent
# model written to settings env, each role's (model, effort), and the concurrency limit.
EXPECTED = {
    "max": dict(
        root=(OPUS, "medium"), default_subagent=HAIKU, concurrency="4",
        roles={"explorer": (HAIKU, "max"), "worker": (HAIKU, "max"), "tester": (HAIKU, "max"),
               "researcher": (HAIKU, "max"), "reviewer": (OPUS, "low")}),
    "pro": dict(
        root=(SONNET, "high"), default_subagent=HAIKU, concurrency="4",
        roles={"explorer": (HAIKU, "medium"), "worker": (HAIKU, "medium"), "tester": (HAIKU, "medium"),
               "researcher": (HAIKU, "medium"), "reviewer": (OPUS, "low")}),
    "max-2-subagents": dict(
        root=(OPUS, "medium"), default_subagent=HAIKU, concurrency="2",
        roles={"explorer": (HAIKU, "max"), "worker": (HAIKU, "max"), "tester": (HAIKU, "max"),
               "researcher": (HAIKU, "max"), "reviewer": (OPUS, "low")}),
    "pro-2-subagents": dict(
        root=(SONNET, "high"), default_subagent=HAIKU, concurrency="2",
        roles={"explorer": (HAIKU, "medium"), "worker": (HAIKU, "medium"), "tester": (HAIKU, "medium"),
               "researcher": (HAIKU, "medium"), "reviewer": (OPUS, "low")}),
    "fable-xhigh-haiku-max": dict(
        root=(FABLE, "xhigh"), default_subagent=HAIKU, concurrency="4",
        roles={"explorer": (HAIKU, "max"), "worker": (HAIKU, "max"), "tester": (HAIKU, "max"),
               "researcher": (HAIKU, "max"), "reviewer": (FABLE, "max")}),
    "fable-medium-haiku-max": dict(
        root=(FABLE, "medium"), default_subagent=HAIKU, concurrency="4",
        roles={"explorer": (HAIKU, "max"), "worker": (HAIKU, "max"), "tester": (HAIKU, "max"),
               "researcher": (HAIKU, "max"), "reviewer": (FABLE, "medium")}),
    "fable-medium-sonnet-high": dict(
        root=(FABLE, "medium"), default_subagent=SONNET, concurrency="4",
        roles={"explorer": (SONNET, "high"), "worker": (SONNET, "high"), "tester": (SONNET, "high"),
               "researcher": (OPUS, "high"), "reviewer": (OPUS, "low")}),
}

# Role frontmatter tool line and color, per the contract.
ROLE_TOOLS = {
    "explorer": ("disallowedTools", "Agent, Write, Edit, NotebookEdit", "cyan"),
    "researcher": ("tools", "Read, Grep, Glob, WebFetch, WebSearch", "purple"),
    "reviewer": ("disallowedTools", "Agent, Write, Edit, NotebookEdit", "red"),
    "tester": ("disallowedTools", "Agent", "yellow"),
    "worker": ("disallowedTools", "Agent", "green"),
}
READ_ONLY_ROLES = ("explorer", "researcher", "reviewer")
MODEL_LABELS = {"claude-opus-5-5": "Opus 5.5", "claude-sonnet-5-5": "Sonnet 5.5",
                "claude-haiku-5-5": "Haiku 5.5", "claude-fable-5-1": "Fable 5.1"}

CODEX_TERMS = [
    "gpt-", "luna", "astra", "sol ", "spawn_agent", "codex", ".codex", "agents.md",
    "sandbox_mode", "approval_policy", "service_tier",
]

TOPOLOGY_LINE = re.compile(r"^- (root|explorer|worker|tester|reviewer|researcher): `([^`]+)` at `([^`]+)` effort$")


def parse_frontmatter(text):
    """Parse the simple `key: value` frontmatter used by agents and skills.

    Returns (ordered list of (key, value), body). Raises AssertionError on
    malformed input so tests report the problem clearly.
    """
    lines = text.split("\n")
    assert lines[0] == "---", "frontmatter must start with ---"
    try:
        end = lines.index("---", 1)
    except ValueError:
        raise AssertionError("frontmatter is not closed with ---")
    pairs = []
    for line in lines[1:end]:
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*): (.+)$", line)
        assert match, f"frontmatter line is not 'key: value': {line!r}"
        pairs.append((match.group(1), match.group(2)))
    body = "\n".join(lines[end + 1:])
    return pairs, body


# Characters that cannot start a plain (unquoted) YAML scalar.
YAML_INDICATORS = set("-?:,[]{}&*!|>'\"%@`#")
YAML_RESERVED = {"true", "false", "yes", "no", "on", "off", "null", "~"}


def yaml_problem(value):
    """Return why an unquoted frontmatter value would not load as a YAML string, or None.

    Claude Code drops an agent or skill file whose frontmatter is invalid YAML,
    and a plain `key: value` regex accepts values that YAML cannot read.
    """
    if not value:
        return "empty value"
    if value != value.strip():
        return "leading or trailing space"
    if ": " in value or value.endswith(":"):
        return "contains a mapping indicator"
    if " #" in value:
        return "contains a comment marker"
    if value[0] in YAML_INDICATORS:
        return f"starts with YAML indicator {value[0]!r}"
    if value.lower() in YAML_RESERVED:
        return "reads as a YAML boolean or null"
    return None


def profile_dir(profile):
    return PROFILES_DIR / profile / "claude"


class SettingsTests(unittest.TestCase):
    def test_settings_values_per_profile(self):
        for profile, expected in EXPECTED.items():
            with self.subTest(profile=profile):
                path = profile_dir(profile) / "settings.json"
                text = path.read_text(encoding="utf-8")
                settings = json.loads(text)
                self.assertEqual(list(settings.keys()), ["$schema", "model", "effortLevel", "env"])
                self.assertEqual(settings["$schema"], "https://json.schemastore.org/claude-code-settings.json")
                self.assertEqual(settings["model"], expected["root"][0])
                self.assertEqual(settings["effortLevel"], expected["root"][1])
                self.assertIn(settings["effortLevel"], ALLOWED_SETTINGS_EFFORT)
                self.assertEqual(settings["env"], {
                    "CLAUDE_CODE_SUBAGENT_MODEL": expected["default_subagent"],
                    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": expected["concurrency"],
                })
                self.assertEqual(text, json.dumps(settings, indent=2) + "\n")

    def test_settings_have_no_codex_keys(self):
        for profile in EXPECTED:
            with self.subTest(profile=profile):
                text = (profile_dir(profile) / "settings.json").read_text(encoding="utf-8")
                for key in ("sandbox_mode", "approval_policy", "service_tier", "model_reasoning_effort"):
                    self.assertNotIn(key, text)


class AgentTests(unittest.TestCase):
    def test_agent_frontmatter_and_tools(self):
        for profile, expected in EXPECTED.items():
            for role in ROLES:
                with self.subTest(profile=profile, role=role):
                    path = profile_dir(profile) / "agents" / f"{role}.md"
                    pairs, body = parse_frontmatter(path.read_text(encoding="utf-8"))
                    self.assertEqual([k for k, _ in pairs],
                                     ["name", "description", "model", "effort", ROLE_TOOLS[role][0], "color"])
                    values = dict(pairs)
                    self.assertEqual(values["name"], role)
                    self.assertTrue(values["description"].strip())
                    model, effort = expected["roles"][role]
                    self.assertEqual(values["model"], model)
                    self.assertEqual(values["effort"], effort)
                    key, tools, color = ROLE_TOOLS[role]
                    self.assertEqual(values[key], tools)
                    self.assertEqual(values["color"], color)
                    self.assertTrue(body.strip())

    def test_read_only_bodies_forbid_bash_modification(self):
        clause = "do not create, modify or delete files through any tool"
        for profile in EXPECTED:
            for role in READ_ONLY_ROLES:
                with self.subTest(profile=profile, role=role):
                    text = (profile_dir(profile) / "agents" / f"{role}.md").read_text(encoding="utf-8")
                    _, body = parse_frontmatter(text)
                    self.assertIn(clause, body.lower())
                    self.assertIn("sed -i", body)

    def test_read_only_roles_cannot_write_tools(self):
        for profile in EXPECTED:
            for role in READ_ONLY_ROLES:
                with self.subTest(profile=profile, role=role):
                    values = dict(parse_frontmatter((profile_dir(profile) / "agents" / f"{role}.md")
                                                    .read_text(encoding="utf-8"))[0])
                    tools = values.get("tools", values.get("disallowedTools", ""))
                    if "disallowedTools" in values:
                        self.assertIn("Write", tools)
                        self.assertIn("Edit", tools)
                    else:
                        self.assertNotIn("Bash", tools)
                        self.assertNotIn("Write", tools)
                        self.assertNotIn("Edit", tools)


class FrontmatterYamlTests(unittest.TestCase):
    def test_yaml_problem_rejects_unsafe_values(self):
        for bad in ["Use for: testing", "trailing colon:", "text # comment", "- item", "[x]",
                    "*alias", "`code`", "true", " padded", ""]:
            with self.subTest(value=bad):
                self.assertIsNotNone(yaml_problem(bad))

    def test_yaml_problem_accepts_plain_values(self):
        for good in ["Read-only repository explorer.", "claude-haiku-5-5", "Opus 5.5", "a#b", "max"]:
            with self.subTest(value=good):
                self.assertIsNone(yaml_problem(good))

    def test_every_frontmatter_value_is_plain_yaml_safe(self):
        paths = sorted(PROFILES_DIR.glob("*/claude/agents/*.md")) + \
            sorted(PROFILES_DIR.glob("*/claude/skills/*/SKILL.md"))
        self.assertTrue(paths, "no agent or skill files found")
        for path in paths:
            pairs, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            for key, value in pairs:
                with self.subTest(path=str(path.relative_to(REPO)), key=key):
                    self.assertIsNone(yaml_problem(value), f"{key}: {value!r}")


class SkillTests(unittest.TestCase):
    def test_skill_frontmatter_and_topology(self):
        for profile, expected in EXPECTED.items():
            with self.subTest(profile=profile):
                path = profile_dir(profile) / "skills" / "claude-orchestrator" / "SKILL.md"
                text = path.read_text(encoding="utf-8")
                pairs, body = parse_frontmatter(text)
                values = dict(pairs)
                self.assertEqual([k for k, _ in pairs], ["name", "description"])
                self.assertEqual(values["name"], "claude-orchestrator")
                self.assertIn(MODEL_LABELS[expected["root"][0]], values["description"])

                found = {}
                for line in body.split("\n"):
                    match = TOPOLOGY_LINE.match(line)
                    if match:
                        found.setdefault(match.group(1), set()).add((match.group(2), match.group(3)))
                for role in ("root",) + ROLES:
                    self.assertIn(role, found, f"no topology line for {role}")
                    want = expected["root"] if role == "root" else expected["roles"][role]
                    self.assertEqual(found[role], {want}, f"topology for {role}")

                self.assertIn(f"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS={expected['concurrency']}", body)
                self.assertIn("`Agent` tool", body)
                self.assertIn(f"`{expected['roles']['explorer'][0]}`", body)
                self.assertNotIn("spawn_agent", body)

    def test_skill_is_full_orchestrator_not_condensed(self):
        for profile in EXPECTED:
            with self.subTest(profile=profile):
                text = (profile_dir(profile) / "skills" / "claude-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
                self.assertGreaterEqual(len(text.split("\n")), 400)
                for heading in ("## Delegation gate", "## Spawn policy", "## Parallelism",
                                "## Escalation behavior", "## Delegated-task completion gate",
                                "## User-facing behavior"):
                    self.assertIn(heading, text)

    def test_wording_follows_each_profiles_models(self):
        for profile, expected in EXPECTED.items():
            with self.subTest(profile=profile):
                text = (profile_dir(profile) / "skills" / "claude-orchestrator" / "SKILL.md").read_text(encoding="utf-8")
                execution, researcher, reviewer = (expected["roles"][role][0]
                                                   for role in ("explorer", "researcher", "reviewer"))
                execution_label, researcher_label, reviewer_label = (
                    MODEL_LABELS[model] for model in (execution, researcher, reviewer))
                if researcher == execution:
                    self.assertNotIn("except the researcher", text)
                    self.assertIn(f"Use {execution_label} for all routine subagent execution.", text)
                    self.assertIn(f"{execution_label} subagents for exploration, implementation, testing, "
                                  "and research", text)
                    self.assertIn(f"The root and reviewer run on the more capable models in this topology; "
                                  f"routine execution subagents run on {execution_label}.", text)
                else:
                    article = "an" if researcher_label[0] in "AEIOU" else "a"
                    self.assertIn(f"Use {execution_label} for all routine subagent execution, except the "
                                  f"researcher, which runs on {researcher_label}.", text)
                    self.assertIn(f"{execution_label} subagents for exploration, implementation, and testing, "
                                  f"{researcher_label} subagents for research", text)
                    self.assertIn(f"spawn {article} {researcher_label} researcher", text)
                    self.assertIn("The root, reviewer, and researcher run on the more capable models", text)
                    self.assertIn(f"routine execution subagents (explorer, worker, and tester) run on "
                                  f"{execution_label}.", text)
                scope = "any role other than `reviewer`"
                if researcher == reviewer:
                    scope += " and `researcher`"
                self.assertIn(f"Do not spawn {reviewer_label} for {scope} unless:", text)
                self.assertIn("Do not claim that a role agent ran on a particular model", text)
                used = {expected["root"][0]} | {model for model, _ in expected["roles"].values()}
                for model, label in MODEL_LABELS.items():
                    if model not in used:
                        self.assertNotIn(label, text)


class CodexLeftoverTests(unittest.TestCase):
    def _scan(self, path, text):
        lowered = text.lower()
        for term in CODEX_TERMS:
            self.assertNotIn(term, lowered, f"Codex term {term!r} found in {path}")

    def test_no_codex_terms_in_profiles(self):
        files = [p for p in PROFILES_DIR.rglob("*") if p.is_file()]
        self.assertTrue(files, "profiles/ has no generated files")
        for path in files:
            with self.subTest(path=str(path.relative_to(REPO))):
                self._scan(path, path.read_text(encoding="utf-8"))

    def test_no_codex_terms_in_claude_md(self):
        self._scan(CLAUDE_MD, CLAUDE_MD.read_text(encoding="utf-8"))


class ClaudeMdTests(unittest.TestCase):
    def test_markers_and_skill_reference(self):
        text = CLAUDE_MD.read_text(encoding="utf-8")
        self.assertEqual(text.count("<!-- claude-orchestrator:start -->"), 1)
        self.assertEqual(text.count("<!-- claude-orchestrator:end -->"), 1)
        self.assertLess(text.index("<!-- claude-orchestrator:start -->"),
                        text.index("<!-- claude-orchestrator:end -->"))
        self.assertIn("claude-orchestrator", text)
        self.assertIn("/claude-orchestrator", text)
        self.assertNotIn("\r", text)
        self.assertTrue(text.endswith("\n"))


class BuildScriptHelperTests(unittest.TestCase):
    def test_relative_key_uses_forward_slashes_for_windows_paths(self):
        base = PureWindowsPath("C:/repo/profiles/max/claude")
        path = PureWindowsPath("C:/repo/profiles/max/claude/skills/claude-orchestrator/SKILL.md")
        self.assertEqual(build_profiles.relative_key(path, base),
                         "skills/claude-orchestrator/SKILL.md")

    def test_check_uses_relative_key_and_accepts_nested_outputs(self):
        profile = build_profiles.PROFILES[0]
        outputs = build_profiles.build_outputs(profile)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "claude"
            for relative, text in outputs.items():
                target = base / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with open(target, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(text)
            with mock.patch.object(build_profiles, "ROOT", root), \
                    mock.patch.object(build_profiles, "generated_dir", return_value=base), \
                    mock.patch.object(build_profiles, "relative_key",
                                      wraps=build_profiles.relative_key) as spy:
                self.assertEqual(build_profiles.check_profile(profile, outputs), [])
                self.assertTrue(spy.called, "check_profile must compute keys with relative_key")

                extra = base / "skills" / "claude-orchestrator" / "NOTES.md"
                extra.write_text("stray\n", encoding="utf-8")
                stale = build_profiles.check_profile(profile, outputs)
            self.assertEqual(len(stale), 1, stale)
            self.assertTrue(stale[0].startswith("unexpected "), stale)
            self.assertTrue(stale[0].endswith("NOTES.md"), stale)


class BuildScriptTests(unittest.TestCase):
    def test_check_passes_on_committed_output(self):
        result = subprocess.run([sys.executable, str(BUILD_SCRIPT), "--check"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_check_detects_stale_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "templates").mkdir()
            shutil.copy(BUILD_SCRIPT, root / "scripts" / "build_profiles.py")
            shutil.copytree(REPO / "templates", root / "templates", dirs_exist_ok=True)
            shutil.copytree(PROFILES_DIR, root / "profiles")
            stale = root / "profiles" / "max" / "claude" / "settings.json"
            stale.write_text(stale.read_text(encoding="utf-8") + " ", encoding="utf-8")
            result = subprocess.run([sys.executable, str(root / "scripts" / "build_profiles.py"), "--check"],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("settings.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
