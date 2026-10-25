# Claude Opus Orchestrator + Haiku Subagents

Install a Claude Code profile with an Opus 5.5, Sonnet 5.5, or Fable 5.1 root
orchestrator, Haiku 5.5 execution subagents, and an independent reviewer.

This is a Claude Code port of
[codex-astra-luna-orchestrator](https://github.com/donvito/codex-astra-luna-orchestrator).
See [Differences from the Codex original](#differences-from-the-codex-original).

## Orchestration topology

The root agent plans, delegates, integrates, and verifies. Execution roles run
on Haiku 5.5. The reviewer runs on a separate model from the execution roles
(Opus 5.5 in most profiles, Fable 5.1 in the Fable profiles).

```text
              root / orchestrator
   Opus 5.5 | Sonnet 5.5 | Fable 5.1  (depends on profile)
                        |
    +-------------------+-------------------+-------------------+
    |                   |                   |                   |
 explorer             worker              tester            researcher
 Haiku 5.5           Haiku 5.5           Haiku 5.5          Haiku 5.5
 read-only                                                  read-only
                        |
                        v
          reviewer (called by root after the work)
          Opus 5.5 (low) | Fable 5.1 (medium or max)
                        |
                        v
          root agent: integrate + verify
```

## Requirements

- Claude Code v2.1.293 or later. `haiku` resolves to Haiku 5.5 from v2.1.293,
  Sonnet 5.5 needs v2.1.284, Opus 5.5 needs v2.1.280, and Fable 5.1 needs
  v2.1.257. Before v2.1.251, `CLAUDE_CODE_SUBAGENT_MODEL` overrode role-file
  model pins, so the reviewer could run on Haiku.
- The profiles pin first-party model IDs. On other providers, see
  [What can override the profile](#what-can-override-the-profile).

## Setup

1. Clone this repository and enter it:

   ```sh
   git clone https://github.com/OrionXV/claude-opus-haiku-orchestrator.git
   cd claude-opus-haiku-orchestrator
   ```

2. Run the installer for your platform:

   macOS/Linux:

   ```sh
   ./setup.sh
   ```

   Windows PowerShell:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   PowerShell 7:

   ```powershell
   pwsh -File .\setup.ps1
   ```

   The installer takes no flags. It reads answers from standard input one line
   at a time, so it can also be piped. It asks the following, in order:

   - `Target repository path: ` (must exist, and must not be this repository)
   - `Select Profile [1-6] (default 1): ` (a number or a profile name)
   - `Install <component>? [Y/n] ` for `.claude/agents`,
     `.claude/skills/claude-orchestrator`, `.claude/settings.json`, and `CLAUDE.md`

   Existing files are never silently replaced. The installer lists any files
   it would overwrite and asks first. Settings are merged, not overwritten (see
   below).

3. Answer the prompts. For example, to install the `pro` profile into
   `../my-project`:

   ```text
   Target repository path: ../my-project
     1) max - Opus 5.5 root, Haiku 5.5 subagents, Opus reviewer (default)
     ...                                   (2-6 list the other profiles)
   Select Profile [1-6] (default 1): 2
   Install .claude/agents? [Y/n]
   Install .claude/skills/claude-orchestrator? [Y/n]
   Install .claude/settings.json? [Y/n]
   Merge into existing .claude/settings.json? [y/N] y
   Install CLAUDE.md? [Y/n]
   Appended instructions to CLAUDE.md. Existing contents preserved.
   Setup complete. 4 component(s) installed in /path/to/my-project (profile: pro).
   See guides/ for model, effort and fast-mode options.
   ```

   The `Merge into existing` question appears only when the target already has
   a `.claude/settings.json`. Pressing Enter at a `[Y/n]` prompt accepts the
   default.

### Installed target project

Installing all components into `../my-project` adds these paths alongside the
project's existing files:

```text
my-project/
├── .claude/
│   ├── settings.json
│   ├── agents/
│   │   ├── explorer.md
│   │   ├── researcher.md
│   │   ├── reviewer.md
│   │   ├── tester.md
│   │   └── worker.md
│   └── skills/
│       └── claude-orchestrator/
│           └── SKILL.md
└── CLAUDE.md
```

`profiles/<profile>/claude/` is installed as `<target>/.claude/`. The
repository's root `CLAUDE.md` is the installable instruction snippet, not a
separate guide for this repository. The installer creates `CLAUDE.md` in the
target, or appends the snippet to the target's existing `CLAUDE.md`, between
`<!-- claude-orchestrator:start -->` and `<!-- claude-orchestrator:end -->`
markers. Running the installer again skips the snippet if the markers are
already present. The snippet refers to the `claude-orchestrator` skill, which
the installer provides from `profiles/<profile>/claude/skills/`.

## How to use the skill

From the target repository, start Claude Code:

```sh
cd ../my-project
claude
```

Invoke the orchestrator explicitly with the skill command:

```text
/claude-orchestrator Implement the invoice export endpoint. Use the explorer to map the path,
a worker to implement it, and the tester and reviewer to verify it.
```

Claude may also pick the skill up on its own when a task matches its
description. The root delegates by calling the `Agent` tool with
`subagent_type` set to a role name (`explorer`, `worker`, `tester`,
`researcher`, `reviewer`). Several `Agent` calls in one message run in parallel.

## Profiles

| # | Profile | Root (model / effort) | Explorer, worker, tester, researcher | Reviewer | Max concurrent subagents (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`) |
|---|---|---|---|---|---:|
| 1 (default) | `max` | `claude-opus-5-5` / medium | `claude-haiku-5-5` / max | `claude-opus-5-5` / low | 4 |
| 2 | `pro` | `claude-sonnet-5-5` / high | `claude-haiku-5-5` / medium | `claude-opus-5-5` / low | 4 |
| 3 | `max-2-subagents` | `claude-opus-5-5` / medium | `claude-haiku-5-5` / max | `claude-opus-5-5` / low | 2 |
| 4 | `pro-2-subagents` | `claude-sonnet-5-5` / high | `claude-haiku-5-5` / medium | `claude-opus-5-5` / low | 2 |
| 5 | `fable-xhigh-haiku-max` | `claude-fable-5-1` / xhigh | `claude-haiku-5-5` / max | `claude-fable-5-1` / max | 4 |
| 6 | `fable-medium-haiku-max` | `claude-fable-5-1` / medium | `claude-haiku-5-5` / max | `claude-fable-5-1` / medium | 4 |

The `max` and `pro` names echo the Claude Max and Pro subscription plans. Each
profile is ready to copy from `profiles/<profile>/claude/`.

Each role file pins its own model and effort, so the profile's default subagent
settings only apply to subagents without a pinned role.

Guides:

- [Max profile and manual project setup](guides/full-orchestration.md)
- [Pro profile and global setup](guides/pro-plan.md)
- [Complex repository work](guides/complex-repo-work.md) (root override)
- [Fast iteration](guides/fast-iteration.md) (root override)
- [Routine coding](guides/routine-coding.md) (root override)
- [Token usage and measurement](guides/token-usage.md)

## Manual setup

For a single project, copy the profile by hand:

1. Copy the contents of `profiles/<profile>/claude/` into `<target>/.claude/`.
   If `<target>/.claude/settings.json` already exists, merge the keys instead
   of replacing the file.
2. Add the repository's root `CLAUDE.md` snippet to the target's `CLAUDE.md`,
   inside the start/end markers.

For a personal setup that applies to every project, use user-level locations:

1. Copy `profiles/<profile>/claude/agents/*.md` to `~/.claude/agents/`.
2. Copy `profiles/<profile>/claude/skills/claude-orchestrator/` to
   `~/.claude/skills/claude-orchestrator/`.
3. **Merge**, do not replace, the keys from `profiles/<profile>/claude/settings.json`
   into `~/.claude/settings.json`. Keep every other key you already have.

Be aware of two effects of user-level setup. Setting `model` in user settings
changes the default model for every project. And, per the Claude Code docs, a
top-level `effortLevel` in user settings applies only to Opus 5, Fable 5.1, and
earlier models. Opus 5.5 and models released after it ignore it, so prefer
project settings for root effort. See
[guides/pro-plan.md](guides/pro-plan.md) for details.

Role names (`explorer`, `worker`, `tester`, `reviewer`, `researcher`) are not
prefixed. Project agents take precedence over user agents with the same name,
and copying the profile's files over a same-named file overwrites it. If you
already have agents with these names, rename them before a user-level install.

### Project trust

Claude Code applies some project settings only after you trust the project
folder. The profile's two `env` keys, `CLAUDE_CODE_SUBAGENT_MODEL` and
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, are model selection and limit settings.
The env-var docs describe variables of that kind as safe, applying at startup
from every settings file rather than only after trust. The docs do not list
these two keys by name. If the orchestrator still uses the wrong model or
concurrency limit, run Claude Code with `claude --debug`, which logs any `env`
variable Claude Code ignored, and check the trust prompt.

### What can override the profile

- **Shell environment.** `CLAUDE_CODE_EFFORT_LEVEL` set in your shell overrides
  `--effort`, `/effort`, and every `effortLevel` setting, so it changes the root
  and every role's effort. A role file's `effort` does not override it. An
  `ANTHROPIC_MODEL` exported in the shell overrides the `model` key.
- **Settings precedence.** Managed settings outrank the project's
  `.claude/settings.json`, and the command line and `settings.local.json` rank
  above it. A managed `effortLevel` or `model` therefore replaces the profile's
  root values, and `maxEffortLevel` can cap effort.
- **Subagent model.** A `model` argument the root passes to the `Agent` tool
  overrides a role's pinned model for that call. `CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1`
  forces one model onto every subagent, including the reviewer.
- **Other providers.** The profiles pin first-party IDs (`claude-opus-5-5`,
  `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-1`). Amazon Bedrock,
  Google Cloud's Agent Platform, Microsoft Foundry, and Claude Platform on AWS
  may not offer every one of these, and their `haiku` and `sonnet` aliases resolve
  to older models. Check your provider's model list and edit the `model` lines in
  `.claude/settings.json` and `.claude/agents/*.md` to match.

## Key directory structure

```text
.
├── profiles/
│   ├── max/
│   ├── pro/
│   ├── max-2-subagents/
│   ├── pro-2-subagents/
│   ├── fable-xhigh-haiku-max/
│   └── fable-medium-haiku-max/
├── templates/                 # source for profiles/, edit here
├── guides/
├── scripts/
│   ├── build_profiles.py      # regenerates profiles/ from templates/
│   └── token_usage.py
├── tests/
│   ├── test_profiles.py
│   ├── test_installers.py
│   └── test_token_usage.py
├── CLAUDE.md                  # instruction snippet installed into targets
├── setup.sh
├── setup.ps1
├── NOTICE
├── README.md
└── LICENSE
```

Each profile contains `claude/settings.json`, `claude/agents/*.md` (five role
files), and `claude/skills/claude-orchestrator/SKILL.md`.

## Testing

From the repository root:

```sh
python3 -m unittest discover -s tests -t .
```

The tests use only the standard library. Tests that need `pwsh` are skipped
when it is not on `PATH`.

Profiles are generated. After editing anything under `templates/` or the
`PROFILES` table, regenerate them:

```sh
python3 scripts/build_profiles.py
python3 scripts/build_profiles.py --check
```

Do not edit files under `profiles/` by hand; the next regeneration overwrites
them.

## Differences from the Codex original

- **Settings are merged, not overwritten.** The installer sets `model`,
  `effortLevel`, `$schema` (if missing), and the two `env` keys in an existing
  `.claude/settings.json` and keeps every other key. It lists the keys it will
  change and asks first. Invalid JSON is never overwritten; the installer skips
  the file with a message.
- **Instructions use markers.** The `CLAUDE.md` snippet sits between
  `<!-- claude-orchestrator:start -->` and `<!-- claude-orchestrator:end -->`,
  so re-running the installer is idempotent.
- **`@AGENTS.md` handling.** Claude Code reads `AGENTS.md` only when no
  `CLAUDE.md` exists. If the target has an `AGENTS.md` and no `CLAUDE.md`, the
  installer creates `CLAUDE.md` starting with `@AGENTS.md`, so the existing
  instructions still load. If the target already has a `CLAUDE.md`, the
  installer appends the snippet and does not add an import. Claude then ignores
  `AGENTS.md` unless you add `@AGENTS.md` yourself.
- **Full skill in every profile.** Every profile ships the complete
  `claude-orchestrator` skill. The skill is not split by profile.
- **Generated profiles.** `profiles/` is produced by
  `scripts/build_profiles.py` from `templates/` and a `PROFILES` table.
- **Read-only roles are limited by tool lists and by prompt.** `sandbox_mode =
  "read-only"` has no equivalent here. The `explorer` and `reviewer` roles remove
  the write tools (`Write`, `Edit`, `NotebookEdit`) with `disallowedTools`, but
  keep Bash (PowerShell on Windows) and MCP tools. The `researcher` role uses an
  allowlist (`Read`, `Grep`, `Glob`, `WebFetch`, `WebSearch`) with no shell or MCP
  tools. Shell writes from `explorer` and `reviewer` are prohibited by the role
  prompt only. Bash is not sandboxed, and subagents inherit the session's
  permission mode, so under `acceptEdits`, `auto`, or `bypassPermissions` some
  shell writes can run without a prompt. No hooks enforce the read-only rule.
- **Roles cannot spawn agents.** Every role excludes the `Agent` tool. Only the
  root delegates.
- **Models and effort.** Models are Opus 5.5, Sonnet 5.5, Haiku 5.5, and Fable
  5.1 instead of GPT-6 Astra, Sol, and Luna. Settings `effortLevel` accepts
  `low`, `medium`, `high`, and `xhigh`; agent `effort` frontmatter also accepts
  `max`. The profile table therefore uses `max` only for subagent and reviewer
  roles, never for the root.
- **Fast mode.** Claude Code's `/fast` replaces the Codex `service_tier` setting.

## Credits

Derived from
[donvito/codex-astra-luna-orchestrator](https://github.com/donvito/codex-astra-luna-orchestrator)
by its authors. See [NOTICE](NOTICE).

## License

Licensed under the [Apache License 2.0](LICENSE).
