# Fable Medium Sonnet Profile: Fable Root, Sonnet Subagents

Choose this profile when you want a Fable 5.1 root at `medium` effort to plan,
delegate, and integrate, with Sonnet 5.5 execution subagents at `high` effort
instead of Haiku 5.5. It also adds an Opus 5.5 researcher for documentation and
version checks and an Opus 5.5 reviewer at `low` effort. Select
`fable-medium-sonnet-high` (choice 7) in `setup.sh` or `setup.ps1`.

Use it when Haiku 5.5 subagents are not strong enough for the execution work,
and you accept the higher cost of Sonnet 5.5 subagents for stronger execution.
For routine work, the Haiku profiles cost less.

Setup copies `profiles/fable-medium-sonnet-high/claude/` to `.claude/` in the
target repository. For manual installation, copy the same contents and add the
repository's `CLAUDE.md` snippet to the target.

## Topology

```text
              root / orchestrator
            Fable 5.1 (medium)
                     |
   +-------------+---+---------+-------------+
   |             |             |             |
explorer      worker        tester       researcher
Sonnet 5.5    Sonnet 5.5    Sonnet 5.5   Opus 5.5
(high)        (high)        (high)       (high)
read-only                                read-only
                     |
                     v
       reviewer (called by root after the work)
            Opus 5.5 (low), read-only
                     |
                     v
         root agent: integrate + verify
```

Each role file pins its own model and effort, so the researcher stays on Opus
5.5 even though the other execution roles run on Sonnet 5.5.

## Root and default subagent settings

The installed `.claude/settings.json` contains:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "model": "claude-fable-5-1",
  "effortLevel": "medium",
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "claude-sonnet-5-5",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"
  }
}
```

`CLAUDE_CODE_SUBAGENT_MODEL` is the default for subagents without a pinned role.
The five role files in `.claude/agents/` set the models and efforts that the
roles actually use. `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` limits how many
subagents run at once.

## When to use it

- Multi-file implementation or debugging where Haiku 5.5 workers have needed
  too much correction.
- Test writing and validation that need more judgment than a Haiku tester gives.
- Version-specific or documentation questions: the Opus researcher checks
  current APIs and framework behavior against primary sources.
- Independent review by a different model from the Fable root, at `low` effort.
  Raise the reviewer's effort in `reviewer.md` for high-risk changes.

For one-file edits and simple questions, do not delegate at all. For bulk
exploration where Haiku is accurate enough, the Haiku profiles are the cheaper
choice.

## Setup

Run the installer and choose `7`, or copy the profile by hand as described in
the [README](../README.md#manual-setup). Check the installed files:

```sh
grep -E '^(model|effort):' .claude/agents/*.md
```

Expected: `explorer`, `worker`, and `tester` show `claude-sonnet-5-5` with
`effort: high`; `researcher` shows `claude-opus-5-5` with `effort: high`;
`reviewer` shows `claude-opus-5-5` with `effort: low`.

Root effort is set in project settings. A managed setting, a shell variable such
as `CLAUDE_CODE_EFFORT_LEVEL`, or a command-line option overrides it. See the
README's [What can override the profile](../README.md#what-can-override-the-profile).
