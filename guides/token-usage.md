# Token Usage

There is no single token number for this setup. Usage depends on repository
size, task shape, how many subagents the root actually spawns, and how much
of each subagent's context is served from cache. This guide gives you a
repeatable way to measure your own runs, the caveats for reading the numbers,
and a placeholder for a sample run.

## What Claude Code records

Claude Code writes one transcript per session under
`~/.claude/projects/<slug>/<session>.jsonl`, or under `$CLAUDE_CONFIG_DIR/projects`
when `CLAUDE_CONFIG_DIR` is set. The `<slug>` is the project's absolute path with
every non-alphanumeric character replaced by `-` (for example
`/Users/me/my-project` becomes `-Users-me-my-project`). Slugs longer than 200
characters are cut to 200 and suffixed with a hash. Subagent transcripts sit
beside it, under `<session>/subagents/agent-<id>.jsonl`.

`scripts/token_usage.py` reads the root transcript and every subagent
transcript for a session, then groups them as one task. For each thread it
reports the role, model, effort (when recorded), responses, input, cache
write, cache read, output, total tokens, and duration. It also reports totals
per model, the cache hit rate, and wall time.

Cache hit rate is `cache_read / (input + cache_write + cache_read)`.

## Measuring a run

`scripts/token_usage.py` is standard-library Python 3.10+ and read-only.

```bash
# List sessions, newest first, on a given day (default 20 rows; each row shows its subagent count)
python3 scripts/token_usage.py --list --date 2026-10-26

# Show more sessions for one project
python3 scripts/token_usage.py --list --limit 50 --project ../my-project

# Report on the newest session that used subagents
python3 scripts/token_usage.py --latest --date 2026-10-26

# Report on one session; any unique id prefix works
python3 scripts/token_usage.py --session 3f9c

# Machine-readable output
python3 scripts/token_usage.py --session 3f9c --format json
```

Flags:

| Flag | Meaning |
|---|---|
| `--list` | List sessions, newest first. Use `--limit N` to change the default of 20. |
| `--session <id-or-prefix>` | Report one session. An ambiguous prefix exits with 2. |
| `--latest` | Report the newest session that has subagents. |
| `--date YYYY-MM-DD` | Keep only sessions that started on this local date. |
| `--project <path>` | Keep sessions for that working directory: those in its project directory, plus any whose recorded working directory is that path (this covers remote `ssh-*` directories). |
| `--projects-dir <path>` | Read from a directory other than the default. The default is `$CLAUDE_CONFIG_DIR/projects` when `CLAUDE_CONFIG_DIR` is set, otherwise `~/.claude/projects`. |
| `--format md\|json` | Output format. Default is `md`. |

Exit codes: `0` on success, `1` when nothing was found, `2` for bad arguments
or an ambiguous session prefix.

Scope and speed: every listing reads only the first lines of each transcript
to get its start time and cwd. `--list` does not parse transcripts; it counts
subagent files only for the rows it prints. `--date` does not avoid that
first-line read, because the start date comes from it. `--project` narrows the
work: the matching project directory is used in full, and other directories are
checked only up to their first `cwd` line. `--session` and `--latest` parse the
project directory of the reported session, since a resumed session stays in the
directory it started in. Without `--project`, every project directory gets the
first-line read.

For a comparison, run the same command on a session that used no subagents.
The script handles sessions with zero subagents.

## Built-in alternative

`/usage` inside Claude Code shows your current usage against your plan limits.
Take a reading before and after a run for a quick, account-level view. It does
not split usage by thread or model; use the script for that.

## Benchmark protocol

Use this protocol if you want numbers that are comparable across configurations:

1. Pick three or four representative tasks in one repository: a single-file
   fix, a multi-file feature, a cross-component bug, and a research-heavy
   change. Write the prompts down and reuse them verbatim.
2. Run each task in at least two configurations:
   - Baseline: the root model alone, with no `.claude/agents/` files, no
     orchestrator skill, and no subagents.
   - Orchestrated: the selected profile as installed.
   - Optional floor: Haiku 5.5 as the root alone, for the cheapest possible run.
3. Record for every run: per-model input, cache write, cache read, and output
   tokens; the number of subagents spawned; wall time; and the `/usage` reading
   before and after.
4. Repeat each cell two or three times. Variance between runs of the same
   prompt is large enough that a single sample misleads.
5. Record the profile and any overrides, such as the Sonnet root at `medium`.
   Note the Claude Code version (`claude --version`). Caching behavior and
   subagent context handling can change between releases.

Suggested results table:

| Task | Config | Root uncached / cache read / out | Haiku uncached / cache read / out | Subagents | Wall | `/usage` before → after |
|---|---|---|---|---:|---:|---|

## Reading the numbers

Compare uncached input and output separately. The total token count includes
cache reads, which are usually the bulk of input, so a raw total overstates the
work done. Check cache reads against cache writes in your own run before
drawing conclusions.

Subscription limits are not published as a function of tokens. The `/usage`
change is the most direct measure of what a task cost against your plan. It is
account-wide, so other sessions running at the same time inflate it.

The root is usually the largest line item, even at `low` or `medium` effort. It
stays active for the whole task, waits on subagents, and re-reads its context on
every response. Parallelism trades tokens for latency, because each spawned
subagent re-reads its own context on every response.

## Sample run

_Not yet measured. To be filled with a real measurement: task, profile and any
overrides, Claude Code version, the script's per-thread table, and the `/usage`
change. The Codex numbers from the original project do not apply to this setup._

## Reducing usage

In rough order of impact:

- Use the `pro` profile (Sonnet 5.5 root) when the Opus root is more than the
  task needs. The root is the largest line item in every orchestrated session.
  See [pro-plan.md](pro-plan.md).
- Do not orchestrate small tasks. Do not invoke `/claude-orchestrator` for a
  one-file edit.
- Keep `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` low. Each extra concurrent
  subagent is another full context re-read on every response. The `-2-subagents`
  profiles set it to 2.
- Ask subagents for short reports. Raw logs pasted into the root are re-read
  on every later root response.
- Skip the reviewer for low-risk changes. It re-reads the diff and its
  surrounding context.
- Lower the explorer's or tester's `effort` in their role files. Output and
  reasoning tokens are a small share of the total, so this mainly shortens
  wall time.

## Contributing results

If you run the protocol on your own projects, open a pull request adding a row
to the suggested results table. Include the task description, repository size,
Claude Code version, plan type, and the script output. Redact any repository
paths you do not want published.
