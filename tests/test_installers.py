"""Behavioural tests for setup.sh and setup.ps1.

Each test copies setup.sh, setup.ps1, CLAUDE.md and profiles/ into a temporary source
directory, runs the installer with scripted stdin against a temporary target, and checks the
result. Checks in InstallerTests run for both installers; the pwsh variants are skipped when
pwsh is not on PATH.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import build_profiles  # noqa: E402
PROFILES = [
    "max",
    "pro",
    "max-2-subagents",
    "pro-2-subagents",
    "fable-xhigh-haiku-max",
    "fable-medium-haiku-max",
    "fable-medium-sonnet-high",
]
PWSH = shutil.which("pwsh")
PWSH_SKIP_REASON = "pwsh is not on PATH"
EOF_MESSAGE = "Setup cancelled: input ended before setup was complete."
REFUSAL_MESSAGE = (
    "Error: target repository must be different from the setup source directory."
)
MISSING_TARGET_MESSAGE = "Error: target must be an existing directory"
SOURCE_FILES = ("setup.sh", "setup.ps1", "CLAUDE.md")
AGENT_NAMES = ("explorer", "worker", "tester", "reviewer", "researcher")
AS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def tree_files(root):
    """Sorted relative paths of regular files under root (empty when root is missing)."""
    if not root.is_dir():
        return []
    return sorted(
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )


def tree_bytes(root):
    """Map of relative path to bytes for every regular file under root."""
    if not root.is_dir():
        return {}
    return {str(relative): (root / relative).read_bytes() for relative in tree_files(root)}


def install_lines(target, profile="", agents="", skills="", settings="", claude_md=""):
    """Scripted stdin for a full install: target, profile, then one answer per component."""
    return [str(target), profile, agents, skills, settings, claude_md]


class InstallerTests:
    """Checks shared by the sh and pwsh installers. Subclasses provide command()."""

    def command(self, source):
        raise NotImplementedError

    def setUp(self):
        self.source = self.make_dir("installer-source-")
        for name in SOURCE_FILES:
            shutil.copy2(REPO_ROOT / name, self.source / name)
        shutil.copytree(REPO_ROOT / "profiles", self.source / "profiles")
        self.target = self.make_dir("installer-target-")

    def make_dir(self, prefix):
        path = Path(tempfile.mkdtemp(prefix=prefix))
        self.addCleanup(shutil.rmtree, path, ignore_errors=True)
        return path

    def make_source_copy(self, parent):
        """A second, independent copy of the installer sources under parent/repo."""
        repo = parent / "repo"
        repo.mkdir()
        for name in SOURCE_FILES:
            shutil.copy2(REPO_ROOT / name, repo / name)
        shutil.copytree(REPO_ROOT / "profiles", repo / "profiles")
        return repo

    def run_installer(self, lines, source=None, trailing_newline=True, env=None):
        source = source or self.source
        text = "".join(f"{line}\n" for line in lines)
        if not trailing_newline:
            text = text[:-1]
        return subprocess.run(
            self.command(source),
            input=text,
            capture_output=True,
            text=True,
            cwd=str(source),
            timeout=120,
            env=env,
        )

    @staticmethod
    def output(result):
        return result.stdout + result.stderr

    @staticmethod
    def snippet():
        return (REPO_ROOT / "CLAUDE.md").read_bytes()

    def assert_profile_installed(self, profile, target):
        profile_claude = REPO_ROOT / "profiles" / profile / "claude"
        installed_claude = target / ".claude"

        for relative in tree_files(profile_claude / "agents"):
            with self.subTest(file=str(relative)):
                self.assertEqual(
                    (installed_claude / "agents" / relative).read_bytes(),
                    (profile_claude / "agents" / relative).read_bytes(),
                )
        self.assertEqual(
            tree_files(installed_claude / "agents"),
            tree_files(profile_claude / "agents"),
        )

        skill = Path("skills") / "claude-orchestrator"
        for relative in tree_files(profile_claude / skill):
            with self.subTest(file=str(skill / relative)):
                self.assertEqual(
                    (installed_claude / skill / relative).read_bytes(),
                    (profile_claude / skill / relative).read_bytes(),
                )

        self.assertEqual(
            (installed_claude / "settings.json").read_bytes(),
            (profile_claude / "settings.json").read_bytes(),
        )
        self.assertEqual((target / "CLAUDE.md").read_bytes(), self.snippet())

    def test_blank_profile_installs_default_max(self):
        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Setup complete. 4 component(s) installed in", result.stdout)
        self.assertIn("(profile: max).", result.stdout)
        self.assert_profile_installed("max", self.target)

    def test_each_profile_selected_by_number(self):
        for number, profile in enumerate(PROFILES, start=1):
            with self.subTest(profile=profile):
                target = self.make_dir("installer-target-")
                result = self.run_installer(install_lines(target, str(number)))

                self.assertEqual(result.returncode, 0, self.output(result))
                self.assertIn(f"(profile: {profile}).", result.stdout)
                self.assert_profile_installed(profile, target)

    def test_each_profile_selected_by_name(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                target = self.make_dir("installer-target-")
                result = self.run_installer(install_lines(target, profile))

                self.assertEqual(result.returncode, 0, self.output(result))
                self.assertIn(f"(profile: {profile}).", result.stdout)
                self.assert_profile_installed(profile, target)

    def test_menu_lists_every_profile_with_its_number(self):
        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(f"Select Profile [1-{len(PROFILES)}] (default 1): ", result.stdout)
        for number, profile in enumerate(PROFILES, start=1):
            with self.subTest(profile=profile):
                self.assertIn(f"  {number}) {profile} - ", result.stdout)
        self.assertIn(
            "  7) fable-medium-sonnet-high - Fable 5.1 root, Sonnet 5.5 subagents, "
            "Opus 5.5 researcher and reviewer",
            result.stdout,
        )

    def test_profile_selected_by_name_is_case_insensitive(self):
        result = self.run_installer(install_lines(self.target, "Fable-Medium-Haiku-Max"))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("(profile: fable-medium-haiku-max).", result.stdout)
        self.assert_profile_installed("fable-medium-haiku-max", self.target)

    def test_refuses_source_directory_as_target(self):
        result = self.run_installer([str(self.source)])

        self.assertEqual(result.returncode, 1)
        self.assertIn(REFUSAL_MESSAGE, self.output(result))

    def test_target_inside_source_is_refused(self):
        nested = self.source / "nested-target"
        nested.mkdir()

        result = self.run_installer([str(nested)])

        self.assertEqual(result.returncode, 1)
        self.assertIn(REFUSAL_MESSAGE, self.output(result))
        self.assertEqual(list(nested.iterdir()), [])

    def test_source_inside_target_is_refused(self):
        outer = self.make_dir("installer-outer-")
        repo = self.make_source_copy(outer)

        result = self.run_installer([str(outer)], source=repo)

        self.assertEqual(result.returncode, 1)
        self.assertIn(REFUSAL_MESSAGE, self.output(result))
        self.assertEqual(sorted(path.name for path in outer.iterdir()), ["repo"])

    def test_missing_target_is_rejected(self):
        result = self.run_installer([str(self.target / "does-not-exist")])

        self.assertEqual(result.returncode, 1)
        self.assertIn(MISSING_TARGET_MESSAGE, self.output(result))

    def test_tilde_target_is_expanded_to_home(self):
        home = self.make_dir("installer-home-")
        repo = home / "repo"
        repo.mkdir()
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))

        result = self.run_installer(install_lines(Path("~/repo")), env=env)

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("(profile: max).", result.stdout)
        self.assert_profile_installed("max", repo)

    def test_eof_at_target_prompt_cancels(self):
        result = self.run_installer([])

        self.assertEqual(result.returncode, 1)
        self.assertIn(EOF_MESSAGE, self.output(result))

    def test_eof_at_install_prompt_cancels(self):
        result = self.run_installer([str(self.target), ""])

        self.assertEqual(result.returncode, 1)
        self.assertIn(EOF_MESSAGE, self.output(result))

    def test_final_answer_without_newline_is_accepted(self):
        # Only the last answer lacks a newline; earlier installs must not be cut short.
        result = self.run_installer(
            install_lines(self.target, claude_md="y"), trailing_newline=False
        )

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertNotIn(EOF_MESSAGE, self.output(result))
        self.assertEqual((self.target / "CLAUDE.md").read_bytes(), self.snippet())
        self.assert_profile_installed("max", self.target)

    def test_claude_md_is_appended_once(self):
        original = b"# Project notes\n"
        (self.target / "CLAUDE.md").write_bytes(original)

        first = self.run_installer(install_lines(self.target))
        self.assertEqual(first.returncode, 0, self.output(first))
        self.assertIn(
            "Appended instructions to CLAUDE.md. Existing contents preserved.",
            first.stdout,
        )
        appended = (self.target / "CLAUDE.md").read_bytes()
        self.assertEqual(appended, original + b"\n\n" + self.snippet())

        second = self.run_installer([str(self.target), "", "n", "n", "n", "y"])
        self.assertEqual(second.returncode, 0, self.output(second))
        self.assertIn("Skipped CLAUDE.md: instructions already present.", second.stdout)
        self.assertEqual((self.target / "CLAUDE.md").read_bytes(), appended)

    def test_agents_md_is_imported_when_claude_md_is_absent(self):
        agents_md = b"# Agents\n"
        (self.target / "AGENTS.md").write_bytes(agents_md)

        result = self.run_installer([str(self.target), "", "n", "n", "n", "y"])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertEqual(
            (self.target / "CLAUDE.md").read_bytes(),
            b"@AGENTS.md\n\n" + self.snippet(),
        )
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), agents_md)
        self.assertFalse((self.target / ".claude").exists())

    def test_claude_dir_agents_md_is_imported_when_claude_md_is_absent(self):
        claude = self.target / ".claude"
        claude.mkdir()
        nested_agents = b"# Nested agents\n"
        (claude / "AGENTS.md").write_bytes(nested_agents)

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertEqual(
            (self.target / "CLAUDE.md").read_bytes(),
            b"@.claude/AGENTS.md\n\n" + self.snippet(),
        )
        self.assertEqual((claude / "AGENTS.md").read_bytes(), nested_agents)

    def test_root_and_claude_dir_agents_md_are_both_imported(self):
        (self.target / "AGENTS.md").write_bytes(b"# Root\n")
        claude = self.target / ".claude"
        claude.mkdir()
        (claude / "AGENTS.md").write_bytes(b"# Nested\n")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertEqual(
            (self.target / "CLAUDE.md").read_bytes(),
            b"@AGENTS.md\n@.claude/AGENTS.md\n\n" + self.snippet(),
        )

    def test_ancestor_agents_md_produces_note(self):
        outer = self.make_dir("installer-outer-")
        (outer / "AGENTS.md").write_bytes(b"# Outer\n")
        project = outer / "project"
        project.mkdir()

        result = self.run_installer(install_lines(project))

        self.assertEqual(result.returncode, 0, self.output(result))
        output = self.output(result)
        self.assertIn(
            "AGENTS.md exists above the target; Claude Code stops reading AGENTS.md files "
            "once a CLAUDE.md is present. Add an @-import if you still need it.",
            output,
        )
        self.assertTrue(
            any(f"{path}/AGENTS.md exists above the target" in output
                for path in {str(outer), str(outer.resolve())}),
            output,
        )

    def test_symlinked_claude_md_is_skipped_with_manual_step(self):
        agents_md = b"# Shared\n"
        (self.target / "AGENTS.md").write_bytes(agents_md)
        os.symlink("AGENTS.md", self.target / "CLAUDE.md")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        output = self.output(result)
        self.assertIn(
            "Skipped CLAUDE.md: it is a symbolic link to AGENTS.md. Append the contents of ",
            output,
        )
        self.assertIn("CLAUDE.md to that file manually.", output)
        self.assertTrue((self.target / "CLAUDE.md").is_symlink())
        self.assertEqual((self.target / "AGENTS.md").read_bytes(), agents_md)

    def test_settings_merge_keeps_unrelated_keys_and_env(self):
        claude = self.target / ".claude"
        claude.mkdir()
        existing = {"theme": "dark", "model": "claude-sonnet-4", "env": {"FOO": "bar"}}
        (claude / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        # profile, agents, skills, settings install, merge confirmation, CLAUDE.md
        result = self.run_installer([str(self.target), "", "", "", "", "y", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Keys that will change in .claude/settings.json:", result.stdout)
        profile = json.loads(
            (REPO_ROOT / "profiles" / "max" / "claude" / "settings.json").read_text()
        )
        merged_text = (claude / "settings.json").read_text()
        merged = json.loads(merged_text)
        self.assertEqual(merged["theme"], "dark")
        self.assertEqual(merged["env"]["FOO"], "bar")
        self.assertEqual(merged["model"], profile["model"])
        self.assertEqual(merged["effortLevel"], profile["effortLevel"])
        self.assertEqual(merged["$schema"], profile["$schema"])
        for key, value in profile["env"].items():
            self.assertEqual(merged["env"][key], value)
        self.assertTrue(merged_text.endswith("\n"))

    def test_settings_merge_preserves_nested_values_and_string_env(self):
        claude = self.target / ".claude"
        claude.mkdir()
        existing = {
            "permissions": {
                "allow": ["Bash(npm test:*)", "Read(./src/**)"],
                "deny": ["Bash(rm -rf:*)"],
            },
            "hooks": {
                "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "echo done"}]}]
            },
            "lastUpdated": "2025-01-02T03:04:05Z",
            "model": "claude-sonnet-4",
            "env": {"FOO": "bar", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": 4},
        }
        (claude / "settings.json").write_text(json.dumps(existing, indent=2) + "\n")

        result = self.run_installer([str(self.target), "", "", "", "", "y", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        merged = json.loads((claude / "settings.json").read_text())
        self.assertEqual(merged["permissions"], existing["permissions"])
        self.assertEqual(merged["hooks"], existing["hooks"])
        self.assertEqual(merged["lastUpdated"], "2025-01-02T03:04:05Z")
        self.assertEqual(merged["env"]["FOO"], "bar")
        # A numeric env value is rewritten as the string the profile declares.
        self.assertEqual(merged["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"], "4")
        self.assertIsInstance(merged["env"]["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"], str)
        self.assertEqual(merged["model"], "claude-opus-5-5")

    def test_declined_settings_merge_leaves_file_unchanged(self):
        claude = self.target / ".claude"
        claude.mkdir()
        original = b'{\n  "theme": "dark"\n}\n'
        (claude / "settings.json").write_bytes(original)

        result = self.run_installer([str(self.target), "", "", "", "", "n", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/settings.json (existing target left unchanged).",
            result.stdout,
        )
        self.assertEqual((claude / "settings.json").read_bytes(), original)

    @unittest.skipIf(AS_ROOT, "root ignores directory permissions")
    @unittest.skipIf(os.name == "nt", "the read-only flag does not block writes to a directory")
    def test_settings_write_failure_is_skipped_and_run_continues(self):
        claude = self.target / ".claude"
        claude.mkdir()
        original = b'{\n  "theme": "dark"\n}\n'
        (claude / "settings.json").write_bytes(original)
        os.chmod(claude, 0o555)
        self.addCleanup(os.chmod, claude, 0o755)

        # agents skipped, skills skipped, settings merge confirmed, CLAUDE.md installed
        result = self.run_installer([str(self.target), "", "n", "n", "y", "y", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Skipped .claude/settings.json: could not write the file.", result.stdout)
        self.assertNotIn("Traceback", self.output(result))
        self.assertIn("Installed CLAUDE.md.", result.stdout)
        self.assertEqual((claude / "settings.json").read_bytes(), original)
        self.assertEqual((self.target / "CLAUDE.md").read_bytes(), self.snippet())

    def test_invalid_settings_json_is_left_untouched(self):
        claude = self.target / ".claude"
        claude.mkdir()
        original = b"{not json\n"
        (claude / "settings.json").write_bytes(original)

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/settings.json: existing file is not valid JSON; left unchanged.",
            self.output(result),
        )
        self.assertEqual((claude / "settings.json").read_bytes(), original)

    def test_second_run_with_same_profile_asks_only_install_prompts(self):
        first = self.run_installer(install_lines(self.target))
        self.assertEqual(first.returncode, 0, self.output(first))
        before = tree_bytes(self.target)

        # Exactly one answer per install prompt: any further prompt would hit end of input.
        second = self.run_installer(install_lines(self.target))

        self.assertEqual(second.returncode, 0, self.output(second))
        output = second.stdout
        self.assertIn("Setup complete. 0 component(s) installed in", output)
        self.assertIn(".claude/agents already up to date.", output)
        self.assertIn(".claude/skills/claude-orchestrator already up to date.", output)
        self.assertIn("nothing to merge.", output)
        self.assertIn("Skipped CLAUDE.md: instructions already present.", output)
        self.assertNotIn("WARNING", output)
        self.assertNotIn("Update .claude", output)
        self.assertEqual(tree_bytes(self.target), before)

    def test_identical_agent_files_are_not_listed_as_overwritten(self):
        first = self.run_installer(install_lines(self.target))
        self.assertEqual(first.returncode, 0, self.output(first))
        agents = self.target / ".claude" / "agents"
        (agents / "explorer.md").write_bytes(b"custom\n")

        # agents install, decline update, skills, settings, CLAUDE.md
        result = self.run_installer([str(self.target), "", "", "n", "", "", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("  - .claude/agents/explorer.md", result.stdout)
        self.assertNotIn("  - .claude/agents/worker.md", result.stdout)
        self.assertEqual((agents / "explorer.md").read_bytes(), b"custom\n")

    def test_declining_agent_overwrite_keeps_existing_file(self):
        agents = self.target / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "explorer.md").write_bytes(b"custom\n")

        # agents install, decline overwrite, skills, settings, CLAUDE.md
        result = self.run_installer([str(self.target), "", "", "n", "", "", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "WARNING: the following existing files will be overwritten:", result.stdout
        )
        self.assertIn("  - .claude/agents/explorer.md", result.stdout)
        self.assertIn(
            "Skipped .claude/agents (existing target left unchanged).", result.stdout
        )
        self.assertEqual((agents / "explorer.md").read_bytes(), b"custom\n")
        self.assertFalse((agents / "worker.md").exists())

    def test_accepting_agent_overwrite_replaces_existing_file(self):
        agents = self.target / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "explorer.md").write_bytes(b"custom\n")

        result = self.run_installer([str(self.target), "", "", "y", "", "", ""])

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Updated .claude/agents.", result.stdout)
        self.assert_profile_installed("max", self.target)

    def test_agent_name_clash_is_listed_before_install(self):
        agents = self.target / ".claude" / "agents"
        agents.mkdir(parents=True)
        (agents / "custom-review.md").write_bytes(
            b'---\nname: "reviewer"\ndescription: Local reviewer\n---\nBody\n'
        )
        (agents / "notes.md").write_bytes(b"---\nname: helper\n---\nBody\n")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        output = result.stdout
        self.assertIn(
            "WARNING: these existing agents use the same name and may shadow the installed ones:",
            output,
        )
        self.assertIn("  - .claude/agents/custom-review.md (name: reviewer)", output)
        self.assertNotIn("notes.md", output)
        self.assertLess(
            output.index("WARNING: these existing agents"),
            output.index("Updated .claude/agents."),
        )
        self.assertTrue((agents / "explorer.md").is_file())

    def test_unrelated_symlink_under_agents_does_not_block_install(self):
        external = self.make_dir("installer-external-")
        external_file = external / "shared.md"
        external_file.write_bytes(b"---\nname: reviewer\n---\nExternal\n")
        agents = self.target / ".claude" / "agents"
        agents.mkdir(parents=True)
        os.symlink(external_file, agents / "linked.md")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Updated .claude/agents.", result.stdout)
        self.assert_profile_installed("max", self.target)
        self.assertTrue((agents / "linked.md").is_symlink())
        self.assertEqual(external_file.read_bytes(), b"---\nname: reviewer\n---\nExternal\n")

    def test_symlink_on_destination_path_skips_agents(self):
        external = self.make_dir("installer-external-")
        external_file = external / "explorer.md"
        external_file.write_bytes(b"external\n")
        agents = self.target / ".claude" / "agents"
        agents.mkdir(parents=True)
        os.symlink(external_file, agents / "explorer.md")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("Skipped .claude/agents", self.output(result))
        self.assertIn("symbolic link", self.output(result))
        self.assertEqual(external_file.read_bytes(), b"external\n")
        self.assertFalse((agents / "worker.md").exists())

    def test_file_where_agents_directory_belongs_is_skipped(self):
        claude = self.target / ".claude"
        claude.mkdir()
        (claude / "agents").write_bytes(b"not a directory\n")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/agents: source and target types are incompatible.",
            self.output(result),
        )
        self.assertEqual((claude / "agents").read_bytes(), b"not a directory\n")


class ShInstallerTests(InstallerTests, unittest.TestCase):
    def command(self, source):
        return ["sh", str(source / "setup.sh")]

    def test_python3_stub_without_json_is_reported_as_missing(self):
        # The macOS /usr/bin/python3 stub exists but fails when developer tools are absent.
        bin_dir = self.make_dir("installer-bin-")
        stub = bin_dir / "python3"
        stub.write_text(
            "#!/bin/sh\n"
            "echo 'xcode-select: note: no developer tools were found' >&2\n"
            "exit 1\n"
        )
        stub.chmod(0o755)
        claude = self.target / ".claude"
        claude.mkdir()
        original = b'{"theme": "dark"}\n'
        (claude / "settings.json").write_bytes(original)
        env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

        result = self.run_installer(install_lines(self.target), env=env)

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/settings.json: python3 is required to merge into an existing file.",
            self.output(result),
        )
        self.assertNotIn("could not read the existing file", self.output(result))
        self.assertEqual((claude / "settings.json").read_bytes(), original)

    def test_symlink_to_source_directory_is_refused(self):
        link = self.make_dir("installer-link-parent-") / "source-link"
        os.symlink(self.source, link)

        result = self.run_installer([str(link)])

        self.assertEqual(result.returncode, 1)
        self.assertIn(REFUSAL_MESSAGE, self.output(result))

    def test_symlinked_agents_directory_is_not_followed(self):
        external = self.make_dir("installer-external-")
        claude = self.target / ".claude"
        claude.mkdir()
        os.symlink(external, claude / "agents")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/agents: the existing target is a symbolic link.",
            self.output(result),
        )
        self.assertEqual(tree_files(external), [])

    def test_symlinked_claude_directory_is_not_followed(self):
        external = self.make_dir("installer-external-")
        os.symlink(external, self.target / ".claude")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn("symbolic link", self.output(result))
        self.assertEqual(tree_files(external), [])

    def test_symlinked_settings_file_is_not_followed(self):
        external = self.make_dir("installer-external-")
        external_file = external / "settings.json"
        external_file.write_bytes(b'{"theme": "dark"}\n')
        claude = self.target / ".claude"
        claude.mkdir()
        os.symlink(external_file, claude / "settings.json")

        result = self.run_installer(install_lines(self.target))

        self.assertEqual(result.returncode, 0, self.output(result))
        self.assertIn(
            "Skipped .claude/settings.json: the existing target is a symbolic link.",
            self.output(result),
        )
        self.assertEqual(external_file.read_bytes(), b'{"theme": "dark"}\n')


class InstallerScriptParityTests(unittest.TestCase):
    """Static checks that setup.sh and setup.ps1 list the same profiles in the same order.

    These run without pwsh, so the PowerShell menu is checked even where the behavioural tests skip.
    """

    def setUp(self):
        self.slugs = [profile["slug"] for profile in build_profiles.PROFILES]
        self.sh = (REPO_ROOT / "setup.sh").read_text(encoding="utf-8")
        self.ps1 = (REPO_ROOT / "setup.ps1").read_text(encoding="utf-8")

    @staticmethod
    def menu(text):
        return [(int(number), slug) for number, slug in re.findall(r"  (\d)\) ([a-z0-9-]+) - ", text)]

    def test_menu_numbers_and_order_match_profiles_table(self):
        expected = list(enumerate(self.slugs, start=1))
        self.assertEqual(self.menu(self.sh), expected)
        self.assertEqual(self.menu(self.ps1), expected)

    def test_powershell_profile_name_array_matches_table(self):
        match = re.search(r"\$profileNames = @\((.*)\)", self.ps1)
        self.assertIsNotNone(match)
        self.assertEqual(re.findall(r"'([a-z0-9-]+)'", match.group(1)), self.slugs)

    def test_shell_case_arms_match_table(self):
        arms = re.findall(r"^\s+.*\|([a-z0-9-]+)\) profile_name=", self.sh, re.MULTILINE)
        self.assertEqual(arms, self.slugs)

    def test_prompt_range_matches_profile_count(self):
        expected = f"[1-{len(self.slugs)}]"
        self.assertIn(f"Select Profile {expected} (default 1): ", self.sh)
        self.assertIn(f"Select Profile {expected} (default 1): ", self.ps1)
        self.assertIn(f"'^[1-{len(self.slugs)}]$'", self.ps1)


@unittest.skipUnless(PWSH, PWSH_SKIP_REASON)
class PwshInstallerTests(InstallerTests, unittest.TestCase):
    def command(self, source):
        return [
            "pwsh",
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(source / "setup.ps1"),
        ]


if __name__ == "__main__":
    unittest.main()
