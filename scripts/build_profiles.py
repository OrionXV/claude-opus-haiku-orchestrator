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
from collections import namedtuple
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "templates"
PROFILES_DIR = ROOT / "profiles"

ROLES = ("explorer", "worker", "tester", "reviewer", "researcher")
# The prose in SKILL.md names one execution model, so these roles must share a model.
EXECUTION_ROLES = ("explorer", "worker", "tester")

SETTINGS_SCHEMA = "https://json.schemastore.org/claude-code-settings.json"

# settings.json effortLevel accepts these; agent frontmatter effort also accepts "max".
ROOT_EFFORTS = ("low", "medium", "high", "xhigh")
ROLE_EFFORTS = ROOT_EFFORTS + ("max",)

MODEL_LABELS = {
    "claude-opus-5-5": "Opus 5.5",
    "claude-sonnet-5-5": "Sonnet 5.5",
    "claude-haiku-5-5": "Haiku 5.5",
    "claude-fable-5-1": "Fable 5.1",
}

Setting = namedtuple("Setting", ("model", "effort"))

# Order is the installer menu order (choice number = position + 1).
# Every role has its own model and effort. default_subagent_model is written to the
# settings env as CLAUDE_CODE_SUBAGENT_MODEL for subagents without a pinned role.
PROFILES = [
    {
        "slug": "max",
        "label": "Max",
        "name": "Max profile",
        "root": Setting("claude-opus-5-5", "medium"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "max"),
            "worker": Setting("claude-haiku-5-5", "max"),
            "tester": Setting("claude-haiku-5-5", "max"),
            "researcher": Setting("claude-haiku-5-5", "max"),
            "reviewer": Setting("claude-opus-5-5", "low"),
        },
        "concurrency": 4,
    },
    {
        "slug": "pro",
        "label": "Pro",
        "name": "Pro profile",
        "root": Setting("claude-sonnet-5-5", "high"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "medium"),
            "worker": Setting("claude-haiku-5-5", "medium"),
            "tester": Setting("claude-haiku-5-5", "medium"),
            "researcher": Setting("claude-haiku-5-5", "medium"),
            "reviewer": Setting("claude-opus-5-5", "low"),
        },
        "concurrency": 4,
    },
    {
        "slug": "max-2-subagents",
        "label": "Max 2-subagents",
        "name": "Max 2-subagents profile",
        "root": Setting("claude-opus-5-5", "medium"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "max"),
            "worker": Setting("claude-haiku-5-5", "max"),
            "tester": Setting("claude-haiku-5-5", "max"),
            "researcher": Setting("claude-haiku-5-5", "max"),
            "reviewer": Setting("claude-opus-5-5", "low"),
        },
        "concurrency": 2,
    },
    {
        "slug": "pro-2-subagents",
        "label": "Pro 2-subagents",
        "name": "Pro 2-subagents profile",
        "root": Setting("claude-sonnet-5-5", "high"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "medium"),
            "worker": Setting("claude-haiku-5-5", "medium"),
            "tester": Setting("claude-haiku-5-5", "medium"),
            "researcher": Setting("claude-haiku-5-5", "medium"),
            "reviewer": Setting("claude-opus-5-5", "low"),
        },
        "concurrency": 2,
    },
    {
        "slug": "fable-xhigh-haiku-max",
        "label": "Fable xhigh",
        "name": "Fable xhigh root profile",
        "root": Setting("claude-fable-5-1", "xhigh"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "max"),
            "worker": Setting("claude-haiku-5-5", "max"),
            "tester": Setting("claude-haiku-5-5", "max"),
            "researcher": Setting("claude-haiku-5-5", "max"),
            "reviewer": Setting("claude-fable-5-1", "max"),
        },
        "concurrency": 4,
    },
    {
        "slug": "fable-medium-haiku-max",
        "label": "Fable medium",
        "name": "Fable medium root profile",
        "root": Setting("claude-fable-5-1", "medium"),
        "default_subagent_model": "claude-haiku-5-5",
        "roles": {
            "explorer": Setting("claude-haiku-5-5", "max"),
            "worker": Setting("claude-haiku-5-5", "max"),
            "tester": Setting("claude-haiku-5-5", "max"),
            "researcher": Setting("claude-haiku-5-5", "max"),
            "reviewer": Setting("claude-fable-5-1", "medium"),
        },
        "concurrency": 4,
    },
    {
        "slug": "fable-medium-sonnet-high",
        "label": "Fable medium Sonnet",
        "name": "Fable medium root, Sonnet subagents profile",
        "root": Setting("claude-fable-5-1", "medium"),
        "default_subagent_model": "claude-sonnet-5-5",
        "roles": {
            "explorer": Setting("claude-sonnet-5-5", "high"),
            "worker": Setting("claude-sonnet-5-5", "high"),
            "tester": Setting("claude-sonnet-5-5", "high"),
            "researcher": Setting("claude-opus-5-5", "high"),
            "reviewer": Setting("claude-opus-5-5", "low"),
        },
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


def validate_profile(profile):
    slug = profile["slug"]
    if set(profile["roles"]) != set(ROLES):
        raise SystemExit(f"{slug}: roles must be exactly {', '.join(ROLES)}")
    if profile["root"].model not in MODEL_LABELS or profile["root"].effort not in ROOT_EFFORTS:
        raise SystemExit(f"{slug}: invalid root setting {tuple(profile['root'])}")
    for role in ROLES:
        setting = profile["roles"][role]
        if setting.model not in MODEL_LABELS or setting.effort not in ROLE_EFFORTS:
            raise SystemExit(f"{slug}: invalid {role} setting {tuple(setting)}")
    if profile["default_subagent_model"] not in MODEL_LABELS:
        raise SystemExit(f"{slug}: unknown default_subagent_model")
    if len({profile["roles"][role].model for role in EXECUTION_ROLES}) != 1:
        raise SystemExit(f"{slug}: {', '.join(EXECUTION_ROLES)} must share one model")
    if profile["roles"]["reviewer"].model == profile["roles"]["explorer"].model:
        raise SystemExit(f"{slug}: reviewer must run on a model other than the execution roles")


def join_names(names):
    quoted = [f"`{name}`" for name in names]
    if len(quoted) <= 2:
        return " and ".join(quoted)
    return ", ".join(quoted[:-1]) + ", and " + quoted[-1]


def profile_context(profile):
    roles = profile["roles"]
    execution_model = roles["explorer"].model
    execution_label = MODEL_LABELS[execution_model]
    researcher_model = roles["researcher"].model
    researcher_label = MODEL_LABELS[researcher_model]
    reviewer_model = roles["reviewer"].model

    # The researcher exception is stated only when its model differs from the execution roles.
    if researcher_model == execution_model:
        researcher_exception = ""
        capable_roles = "root and reviewer"
        routine_clause = f"routine execution subagents run on {execution_label}"
        subagent_summary = f"{execution_label} subagents for exploration, implementation, testing, and research"
    else:
        researcher_exception = f", except the researcher, which runs on {researcher_label}"
        capable_roles = "root, reviewer, and researcher"
        routine_clause = f"routine execution subagents (explorer, worker, and tester) run on {execution_label}"
        subagent_summary = (
            f"{execution_label} subagents for exploration, implementation, and testing, "
            f"{researcher_label} subagents for research"
        )

    # Non-reviewer roles on the reviewer's model are named next to the reviewer in the spawn policy.
    shared = [role for role in ROLES if role != "reviewer" and roles[role].model == reviewer_model]
    reviewer_scope = "any role other than " + join_names(["reviewer"] + shared)

    context = {
        "profile_name": profile["name"],
        "profile_label": profile["label"],
        "root_model": profile["root"].model,
        "root_label": MODEL_LABELS[profile["root"].model],
        "root_effort": profile["root"].effort,
        "execution_label": execution_label,
        "subagent_summary": subagent_summary,
        "researcher_article": "an" if researcher_label[0] in "AEIOU" else "a",
        "researcher_exception": researcher_exception,
        "capable_roles": capable_roles,
        "routine_clause": routine_clause,
        "reviewer_scope": reviewer_scope,
        "concurrency": str(profile["concurrency"]),
    }
    for role in ROLES:
        setting = roles[role]
        context[f"{role}_model"] = setting.model
        context[f"{role}_effort"] = setting.effort
        context[f"{role}_label"] = MODEL_LABELS[setting.model]
    return context


def settings_text(profile):
    settings = {
        "$schema": SETTINGS_SCHEMA,
        "model": profile["root"].model,
        "effortLevel": profile["root"].effort,
        "env": {
            "CLAUDE_CODE_SUBAGENT_MODEL": profile["default_subagent_model"],
            "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": str(profile["concurrency"]),
        },
    }
    return json.dumps(settings, indent=2) + "\n"


def build_outputs(profile):
    """Return {relative path under profiles/<slug>/claude/: text}."""
    validate_profile(profile)
    context = profile_context(profile)
    outputs = {"settings.json": settings_text(profile)}

    for role in ROLES:
        setting = profile["roles"][role]
        role_context = dict(context, model=setting.model, effort=setting.effort)
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
