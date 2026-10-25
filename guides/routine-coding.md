# Routine Coding

Choose this override for predictable, routine coding tasks where lower cost and
faster orchestration are preferred.

This is an optional root override for the [Pro profile](pro-plan.md), which
uses a Sonnet 5.5 root at `high`. It lowers the root to `medium`. The Haiku 5.5
subagents stay at `medium` and the Opus 5.5 reviewer at `low`.

Add or merge these keys into the project's `.claude/settings.json`. Keep the
other keys:

```json
{
  "model": "claude-sonnet-5-5",
  "effortLevel": "medium"
}
```

To change effort for one session only, pick the session-only option (`s`) in
the `/effort` picker. Typing `/effort medium`, or pressing Enter in the picker,
saves the level as the default for the model in your user settings, which
affects other projects.

Per the Claude Code docs, a top-level `effortLevel` in user settings applies only
to Opus 5, Fable 5.1, and earlier models. Because this override targets a Sonnet
root, set it in project settings, not in `~/.claude/settings.json`.

If you change the root's effort level, check whether the installed
`.claude/skills/claude-orchestrator/SKILL.md` mentions the root's effort, and
update that wording to match.
