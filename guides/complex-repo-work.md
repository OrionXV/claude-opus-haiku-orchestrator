# Complex Repository Work

Choose this override for architecture changes, difficult debugging, and work
where higher-confidence reasoning matters more than latency.

This is an optional root override for the [Max profile](full-orchestration.md),
whose root is Opus 5.5 at `medium`. It leaves the Haiku 5.5 roles and the Opus
5.5 `low` reviewer unchanged.

Add or merge these keys into the project's `.claude/settings.json`. Keep the
other keys:

```json
{
  "model": "claude-opus-5-5",
  "effortLevel": "high"
}
```

Use `"xhigh"` in place of `"high"` for even more reasoning. `effortLevel`
accepts `low`, `medium`, `high`, and `xhigh`.

To change effort for one session only, pick the session-only option (`s`) in
the `/effort` picker, or start with `claude --effort high`. Typing `/effort high`,
or pressing Enter in the picker, saves the level as the default for the model in
your user settings, which affects other projects.

Per the Claude Code docs, a top-level `effortLevel` in user settings applies only
to Opus 5, Fable 5.1, and earlier models. Set the level in project settings
instead. If `CLAUDE_CODE_EFFORT_LEVEL` is set in your shell, it overrides `/effort`,
`--effort`, and these settings.

If you change the root's effort level, check whether the installed
`.claude/skills/claude-orchestrator/SKILL.md` mentions the root's effort, and
update that wording to match.
