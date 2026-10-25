# Pro Profile: Sonnet + Haiku Orchestration

Choose this profile for a Sonnet 5.5 root at `high` effort, Haiku 5.5 execution
subagents at `medium` effort, and an Opus 5.5 reviewer at `low` effort. Select
`pro` (choice 2) in `setup.sh` or `setup.ps1`.

Setup copies `profiles/pro/claude/` to `.claude/` in the target repository.
For manual installation, copy the same contents and add the `CLAUDE.md`
snippet to the target.

The reviewer stays on Opus even though the root is Sonnet. It is a single,
read-only, `low`-effort thread, and it gives an independent review by a
different model than the one that planned and wrote the change. To run the
whole session on Sonnet, change `model` in `.claude/agents/reviewer.md` too.

## Project settings

Put these in the project's `.claude/settings.json`:

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "model": "claude-sonnet-5-5",
  "effortLevel": "high",
  "env": {
    "CLAUDE_CODE_SUBAGENT_MODEL": "claude-haiku-5-5",
    "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "4"
  }
}
```

The explorer, worker, tester, and researcher role files pin
`model: claude-haiku-5-5` and `effort: medium`. The reviewer pins
`model: claude-opus-5-5` and `effort: low`.

## Global setup

A global setup applies to every project, so use it only if that is what you
want.

1. Copy `profiles/pro/claude/agents/*.md` to `~/.claude/agents/`.
2. Copy `profiles/pro/claude/skills/claude-orchestrator/` to
   `~/.claude/skills/claude-orchestrator/`.
3. Merge the keys from `profiles/pro/claude/settings.json` into
   `~/.claude/settings.json`. Do not replace the file, and keep other keys.

Two cautions:

- `model` in user settings changes the default model in every project, not
  only the orchestrated ones.
- Per the Claude Code docs, a top-level `effortLevel` in user settings applies
  only to Opus 5, Fable 5.1, and earlier models. Opus 5.5 and models released
  after it ignore it, so the Sonnet root's `high` effort may not take effect
  from the global file. Set it in project settings. Typing `/effort high` saves
  a default for the model in your user settings, which affects other projects.
  Pick the session-only option (`s` in the `/effort` picker) to avoid that.

A project-level `.claude/agents/` definition with the same name takes
precedence over a user-level one, so per-project files still win.
