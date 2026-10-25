#!/usr/bin/env python3
"""Render profiles/<profile>/claude/ from templates/ and the PROFILES table.

Usage:
  python3 scripts/build_profiles.py          write every generated file
  python3 scripts/build_profiles.py --check  exit 1 and list stale files; write nothing

Stdlib only. Output is deterministic, LF line endings, one trailing newline.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
PROFILES_DIR = ROOT / "profiles"

ROLES = ("explorer", "worker", "tester", "reviewer", "researcher")
ROUTINE_ROLES = ("explorer", "worker", "tester", "researcher")

SETTINGS_SCHEMA = "https://json.schemastore.org/claude-code-settings.json"

MODEL_LABELS = {
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-5-5": "Haiku 5.5",
    "claude-fable-5-1": "Fable 5.1",
}

# Order is the installer menu order (choice number = position + 1).
PROFILES = [
    {
        "slug": "max",
        "label": "Max",
        "name": "Max profile",
        "root_model": "claude-opus-5-5",
        "root_effort": "medium",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "max",
        "reviewer_model": "claude-opus-5-5",
        "reviewer_effort": "low",
        "concurrency": 4,
    },
    {
        "slug": "pro",
        "label": "Pro",
        "name": "Pro profile",
        "root_model": "claude-sonnet-5-5",
        "root_effort": "high",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "medium",
        "reviewer_model": "claude-opus-5-5",
        "reviewer_effort": "low",
        "concurrency": 4,
    },
    {
        "slug": "max-2-subagents",
        "label": "Max 2-subagents",
        "name": "Max 2-subagents profile",
        "root_model": "claude-opus-5-5",
        "root_effort": "medium",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "max",
        "reviewer_model": "claude-opus-5-5",
        "reviewer_effort": "low",
        "concurrency": 2,
    },
    {
        "slug": "pro-2-subagents",
        "label": "Pro 2-subagents",
        "name": "Pro 2-subagents profile",
        "root_model": "claude-sonnet-5-5",
        "root_effort": "high",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "medium",
        "reviewer_model": "claude-opus-5-5",
        "reviewer_effort": "low",
        "concurrency": 2,
    },
    {
        "slug": "fable-xhigh-haiku-max",
        "label": "Fable xhigh",
        "name": "Fable xhigh root profile",
        "root_model": "claude-fable-5-1",
        "root_effort": "xhigh",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "max",
        "reviewer_model": "claude-fable-5-1",
        "reviewer_effort": "max",
        "concurrency": 4,
    },
    {
        "slug": "fable-medium-haiku-max",
        "label": "Fable medium",
        "name": "Fable medium root profile",
        "root_model": "claude-fable-5-1",
        "root_effort": "medium",
        "subagent_model": "claude-haiku-5-5",
        "subagent_effort": "max",
        "reviewer_model": "claude-fable-5-1",
        "reviewer_effort": "medium",
        "concurrency": 4,
    },
]

PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


def read_template(relative):
    text = (TEMPLATES / relative).read_text(encoding="utf-8")
    return text.replace("\r\n", "\n")


def render(text, context, source):
    def substitute(match):
        key = match.group(1)
        if key not in context:
            raise SystemExit(f"{source}: unknown placeholder {{{{{key}}}}}")
        return context[key]

    rendered = PLACEHOLDER.sub(substitute, text)
    if "{{" in rendered or "}}" in rendered:
        raise SystemExit(f"{source}: unresolved placeholder remains")
    return rendered.rstrip("\n") + "\n"


def profile_context(profile):
    context = {
        "profile_name": profile["name"],
        "profile_label": profile["label"],
        "root_model": profile["root_model"],
        "root_label": MODEL_LABELS[profile["root_model"]],
        "root_effort": profile["root_effort"],
        "subagent_model": profile["subagent_model"],
        "subagent_label": MODEL_LABELS[profile["subagent_model"]],
        "subagent_effort": profile["subagent_effort"],
        "reviewer_model": profile["reviewer_model"],
        "reviewer_label": MODEL_LABELS[profile["reviewer_model"]],
        "reviewer_effort": profile["reviewer_effort"],
        "concurrency": str(profile["concurrency"]),
    }
    return context


def settings_text(profile):
    settings = {
        "$schema": SETTINGS_SCHEMA,
        "model": profile["root_model"],
        "effortLevel": profile["root_effort"],
        "env": {
            "CLAUDE_CODE_SUBAGENT_MODEL": profile["subagent_model"],
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(profile["concurrency"]),
        },
    }
    return json.dumps(settings, indent=2) + "\n"


def build_outputs(profile):
    """Return {relative path under profiles/<slug>/claude/: text}."""
    context = profile_context(profile)
    outputs = {"settings.json": settings_text(profile)}

    for role in ROLES:
        if role == "reviewer":
            model, effort = profile["reviewer_model"], profile["reviewer_effort"]
        else:
            model, effort = profile["subagent_model"], profile["subagent_effort"]
        role_context = dict(context, model=model, effort=effort)
        source = f"templates/agents/{role}.md.tmpl"
        outputs[f"agents/{role}.md"] = render(read_template(f"agents/{role}.md.tmpl"), role_context, source)

    outputs["skills/claude-orchestrator/SKILL.md"] = render(
        read_template("SKILL.md.tmpl"), context, "templates/SKILL.md.tmpl"
    )
    return outputs


def generated_dir(profile):
    return PROFILES_DIR / profile["slug"] / "claude"


def relative_key(path, base):
    """Return the output key for a generated file: always "/"-separated.

    Output keys are compared with dict keys from build_outputs(), which use
    forward slashes on every platform. str() of a Windows path would use
    backslashes and make every nested file look unexpected.
    """
    return path.relative_to(base).as_posix()


def check_profile(profile, outputs):
    base = generated_dir(profile)
    stale = []
    for relative, expected in outputs.items():
        path = base / relative
        if not path.is_file():
            stale.append(f"missing {path.relative_to(ROOT)}")
            continue
        actual = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if actual != expected:
            stale.append(f"stale {path.relative_to(ROOT)}")
    if base.is_dir():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if relative_key(path, base) not in outputs:
                stale.append(f"unexpected {path.relative_to(ROOT)}")
    return stale


def write_profile(profile, outputs):
    base = generated_dir(profile)
    for relative, text in outputs.items():
        path = base / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    if base.is_dir():
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            if relative_key(path, base) not in outputs:
                path.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="fail if generated files are stale")
    args = parser.parse_args(argv)

    all_outputs = {profile["slug"]: build_outputs(profile) for profile in PROFILES}

    if args.check:
        stale = []
        for profile in PROFILES:
            stale.extend(check_profile(profile, all_outputs[profile["slug"]]))
        if stale:
            for line in stale:
                print(line, file=sys.stderr)
            print("profiles are stale: run python3 scripts/build_profiles.py", file=sys.stderr)
            return 1
        print("profiles are up to date")
        return 0

    count = 0
    for profile in PROFILES:
        write_profile(profile, all_outputs[profile["slug"]])
        count += len(all_outputs[profile["slug"]])
    print(f"wrote {count} files for {len(PROFILES)} profiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
