# Fast Iteration

Choose this override when latency matters and you want Opus 5.5 to orchestrate
quickly with Haiku 5.5 subagents.

Start with the [Max profile](full-orchestration.md). This optional override
keeps the Opus root at `medium` effort. The Haiku roles stay at `max` and the
Opus reviewer at `low`. For a Sonnet root, use the [Pro profile](pro-plan.md).

Turn on fast mode with `/fast`. It runs Opus up to 2.5x faster at a higher price
per token. Run `/fast` again to turn it off.

Fast mode is stored as the `fastMode` key in your user settings file
(`~/.claude/settings.json`). `/fast` writes it, so fast mode persists into later
sessions unless you set `fastModePerSessionOptIn` to `true`, which requires
`/fast` in each session.

On Pro and Max plans, fast mode is billed to usage credits and is not included
in the subscription limits. Check the fast mode docs for current pricing before
relying on it for long sessions. Fast mode is supported on Opus 5.5, Opus 5, and
Opus 4.8. If the session switches to a model that does not support it, fast mode
turns off.

Haiku subagents are not affected. They keep the model and effort pinned in their
role files.
