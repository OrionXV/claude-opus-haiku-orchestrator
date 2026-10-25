# Max Profile: Opus + Haiku Orchestration

Choose this profile when you want Opus 5.5 to plan, delegate, and integrate
while Haiku 5.5 handles execution, with an independent Opus reviewer. Select
`max` (the default, choice 1) in `setup.sh` or `setup.ps1`.

Setup copies `profiles/max/claude/` to `.claude/` in the target repository.
For manual installation, copy the same contents and add the repository's
`CLAUDE.md` snippet to the target.

The topology is:

```text
Opus 5.5 root (medium)
├── Haiku 5.5 explorer (max, read-only)
├── Haiku 5.5 worker (max)
├── Haiku 5.5 tester (max)
├── Haiku 5.5 researcher (max, read-only)
└── Opus 5.5 reviewer (low, read-only)
```

## Root settings

Put these in the project's `.claude/settings.json`:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "model": "claude-opus-5-5",
  "effortLevel": "medium",
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "claude-haiku-5-5",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"
  }
}
```

`CLAUDE_CODE_SUBAGENT_MODEL` sets the default subagent model.
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` caps how many subagents run at once
(the default is 20). An `Agent` call made while the limit is reached fails with
`Concurrent subagent limit reached`, so start the rest of a fan-out as earlier
agents finish.

## Role files

Each file in `.claude/agents/` pins its own model and effort in the frontmatter.
For example, `explorer.md`:

```yaml
---
name: explorer
description: <one-line role description>
model: claude-haiku-5-5
effort: max
disallowedTools: Agent, Write, Edit, NotebookEdit
color: cyan
---
```

The `reviewer.md` file pins `model: claude-opus-5-5` with `effort: low`. The
`worker.md` and `tester.md` files pin Haiku 5.5 at `max`, and `researcher.md`
pins Haiku 5.5 at `max` with a read-only tool list.

Role files override the default subagent settings. Edit them to change a
role's model or effort. Do not rely on the root's `effortLevel` to change them.

"Read-only" here means the role has no write tools and its prompt forbids
writing files. The `explorer` and `reviewer` roles keep Bash and MCP tools, so
shell writes are prevented by the prompt only. See the README's read-only note.

## Manual installation

1. Copy `profiles/max/claude/` to `<target>/.claude/`, merging `settings.json`
   if the target already has one.
2. Add the repository's root `CLAUDE.md` snippet to the target's `CLAUDE.md`
   inside the start and end markers.

For a root at a different model or effort, see the override guides:
[complex-repo-work.md](complex-repo-work.md), [fast-iteration.md](fast-iteration.md),
and [routine-coding.md](routine-coding.md). For the Sonnet root, use the
[Pro profile](pro-plan.md).
