---
name: claude-orchestrator
description: Orchestrate complex Claude Code coding work for the Fable xhigh profile with Fable 5.1 at xhigh effort as planner/integrator, Haiku 5.5 subagents for exploration, implementation, testing, and research, and a separate reviewer on Fable 5.1. Use for multi-file features, debugging across components, repo-wide changes, parallelizable workstreams, or whenever the user asks to delegate or use subagents. Do not use for trivial one-file edits or simple questions.
---

# Claude Orchestrator — Fable xhigh root profile

The user's explicit instructions take precedence over this skill.

## Goal

Use the root agent as the high-quality orchestrator.

Delegate bounded execution work to specialized subagents, then have the root integrate, verify, and present the final result.

The expected default topology is:

- root: `claude-fable-5-1` at `xhigh` effort
- explorer: `claude-haiku-5-5` at `max` effort
- worker: `claude-haiku-5-5` at `max` effort
- tester: `claude-haiku-5-5` at `max` effort
- reviewer: `claude-fable-5-1` at `max` effort
- researcher: `claude-haiku-5-5` at `max` effort

Use Haiku 5.5 for all routine subagent execution.

This is a requirement, not a preference.

The root and reviewer run on the more capable models in this topology; routine execution subagents run on Haiku 5.5.

Do not override a Haiku 5.5 subagent to a more expensive model unless the user explicitly asks for escalation or a Haiku 5.5 worker reports that the task requires higher-level reasoning.

---

## Delegation gate

Before doing substantive repository work, classify the task as either:

- root-only
- delegated

Use root-only only when the task is genuinely small, localized, and does not materially benefit from independent exploration, implementation, testing, research, or review.

The task MUST be delegated when at least one of the following is true:

- the task spans multiple files, modules, services, or components
- there are two or more independent workstreams
- repository exploration is needed before implementation
- implementation and verification benefit from separate context
- debugging requires tracing across components
- multiple modules or services need inspection
- external or version-specific facts need verification
- an independent post-change review is materially useful
- the user explicitly asks for delegation, parallelism, agents, or subagents

When a task qualifies for delegation, the root MUST call the `Agent` tool before performing the delegated work itself.

Do not merely describe, simulate, or internally reason about delegation.

Actual subagents must be spawned.

If the `Agent` tool is unavailable or a call fails, explicitly report that failure.

Do not silently fall back to doing required delegated work in the root thread.

For every delegated task, spawn at least one subagent.

Do not create subagents solely to satisfy this rule when the task is genuinely root-only.

---

## Root-agent responsibilities

The root agent owns:

1. understanding the user's actual goal
2. choosing the architecture and implementation direction
3. decomposing the task
4. deciding which tasks can run in parallel
5. spawning the appropriate subagents
6. giving each subagent a bounded contract
7. resolving conflicting subagent findings
8. integrating changes
9. reviewing the final diff
10. running or coordinating final verification
11. presenting the final result to the user

Subagents provide evidence and bounded execution.

They do not own the overall direction.

The root must not offload architectural ownership to a subagent.

---

## Spawn policy

Each role file in `.claude/agents/` pins its model and effort, so the default models are:

- explorer: `claude-haiku-5-5` at `max` effort
- worker: `claude-haiku-5-5` at `max` effort
- tester: `claude-haiku-5-5` at `max` effort
- researcher: `claude-haiku-5-5` at `max` effort
- reviewer: `claude-fable-5-1` at `max` effort

The root keeps the profile configuration from `.claude/settings.json`: `claude-fable-5-1` at `xhigh` effort. The role files in `.claude/agents/` set the subagent efforts listed above. Preserve those efforts when spawning agents unless the user requests a change. Do not change the root model from within a session.

For every delegated task:

1. call the `Agent` tool with `subagent_type` set to the role: `explorer`, `worker`, `tester`, `reviewer`, or `researcher`
2. give the agent a short description (3-5 words) that names the task
3. leave `model` and `effort` unset, so the role file's pinned model and effort apply
4. give the subagent a bounded delegation contract
5. retain the agent ID or task name that the call returns
6. wait for required agents before final synthesis

Prefer the named role agents for delegated work. Do not use a fork or the `general-purpose` agent in their place: a fork inherits the root's model and full conversation, and `general-purpose` has no pinned model or effort and every tool, so it skips the role's read-only contract.

Do not silently substitute the root agent for a required Haiku 5.5 worker.

Only the root escalates a subagent to a different model or effort. Passing the `model` or `effort` argument to the `Agent` tool overrides the role's pinned value for that one invocation. Do this only when the user has asked for it, or the root has decided a stronger model or higher effort is needed. Never do it because a subagent asks for it.

Do not spawn Fable 5.1 for any role other than `reviewer` unless:

- the user explicitly requests it
- Haiku 5.5 reports a genuinely difficult reasoning blocker
- the root determines that a high-risk architectural or security review needs it

Routine execution should remain on Haiku 5.5.

---

## Delegation contract

Every delegated task should include:

- Objective: one concrete outcome
- Scope: exact files, module, subsystem, or question when known
- Context: only the information needed to succeed
- Constraints: what must not change
- Deliverable: what the subagent must return or implement
- Acceptance criteria: how success will be checked

Prefer narrow tasks that can finish independently.

Bad:

> Fix the backend.

Good:

> Trace where POST /invoices validates currency. Return the responsible files, validation path, and existing tests. Do not edit files.

For implementation tasks, explicitly state file ownership when possible.

For exploration tasks, tell the agent not to edit files.

For review tasks, tell the agent to report findings rather than silently modify unrelated code.

---

## Role selection

Use `explorer` for:

- repository mapping
- tracing execution or data flow
- locating symbols and tests
- dependency inspection
- configuration inspection
- identifying implementation boundaries

Use `worker` for:

- bounded implementation
- small refactors with explicit scope
- targeted fixes
- adding requested code
- modifying clearly owned files

Use `tester` for:

- reproduction
- targeted test execution
- validation
- regression checks
- adding tests when requested or clearly required by the task

Use `reviewer` for:

- independent post-change review
- correctness checks
- security review
- regression analysis
- missing-test analysis
- architectural consistency checks

Use `researcher` for:

- current API or framework behavior
- dependency or version questions
- primary documentation verification
- external compatibility questions

---

## Parallelism

Run independent tasks in parallel.

When two or more delegated tasks are independent, issue all of their `Agent` calls in a single message before waiting for any one of them.

This profile allows at most 4 subagents at once (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=4`). The limit counts running subagents, so an `Agent` call made while the limit is reached fails with `Concurrent subagent limit reached`. Do not retry it immediately: launch at most 4 at once, and start the rest as earlier ones finish.

The three-agent example below needs a limit of at least three. With a smaller limit, start two and start the third when one of them finishes.

Background agents report back through a completion notification. Do not poll them or read their output files while they run. "Wait" means waiting for each agent's result or notification.

Good parallel set:

1. one `Agent` call for the backend explorer
2. one `Agent` call for the frontend explorer
3. one `Agent` call for the API researcher
4. wait for all three
5. synthesize findings

Do not do this:

1. spawn backend explorer
2. wait
3. spawn frontend explorer
4. wait
5. spawn researcher
6. wait

unless later tasks genuinely depend on earlier results.

Good parallel examples:

- explorer maps backend path
- explorer maps frontend path
- researcher verifies external API behavior

Serialize dependent work:

1. explore
2. decide architecture
3. implement
4. test
5. review
6. fix material findings
7. final verification

Do not send multiple workers to edit the same files unless the root explicitly coordinates ownership.

Prefer one writer per file or subsystem.

---

## Default coding workflow

For non-trivial implementation tasks, prefer this sequence:

1. spawn one or more Haiku 5.5 explorers if repository understanding is needed
2. wait for exploration results
3. root decides implementation direction
4. spawn Haiku 5.5 worker or workers with bounded ownership
5. wait for implementation
6. spawn Haiku 5.5 tester
7. wait for validation
8. spawn Fable 5.1 reviewer when an independent review is materially useful
9. resolve material findings
10. run final verification
11. present the result

Do not spawn every role mechanically.

Use only the roles that materially improve the task.

However, once the delegation gate is satisfied, at least one real subagent must be spawned.

---

## Debugging workflow

For cross-component bugs:

1. spawn explorers for independent suspected areas
2. reproduce the issue when possible
3. collect evidence before selecting a fix
4. root determines the likely root cause
5. assign a bounded Haiku 5.5 worker to implement the fix
6. assign a Haiku 5.5 tester to reproduce the original failure and validate the fix
7. use the Fable 5.1 reviewer for high-risk or non-obvious fixes

Do not let multiple workers independently attempt competing fixes unless the root intentionally requests alternative approaches.

---

## Research workflow

When current or version-specific external information matters:

1. spawn a Haiku 5.5 researcher
2. require primary or authoritative sources when possible
3. return concise findings and compatibility implications
4. let the root decide how those findings affect implementation

Do not mix speculative external claims into implementation decisions without verification.

---

## Cost and context discipline

Use Haiku 5.5 for routine subagent execution.

Keep the root context focused on:

- architectural decisions
- summarized evidence
- important diffs
- test results
- reviewer findings
- unresolved risks

Do not paste large raw logs or entire files back into the root when a concise evidence summary is enough.

Subagents should return:

- conclusions
- relevant file paths
- important line or symbol references
- commands run
- test results
- risks or blockers

Avoid returning large amounts of irrelevant raw output.

---

## Escalation behavior

A subagent should report back instead of expanding scope when it encounters:

- an architectural decision
- a breaking API or schema change
- a new dependency
- a security-sensitive design choice
- unclear requirements with materially different outcomes
- unexpected changes outside its assigned scope
- changes that affect another worker's ownership
- a blocker that requires substantially broader reasoning

The root decides what to do next.

A Haiku 5.5 subagent should not escalate itself to a more expensive model.

The root owns model escalation decisions.

---

## Failure handling

If a subagent fails:

1. inspect the failure reason
2. decide whether the task should be retried, narrowed, reassigned, or handled by the root
3. do not silently ignore the failed delegation
4. do not claim the delegated work completed successfully

If the `Agent` call itself fails, explicitly note the failure.

If a required worker fails repeatedly, the root may continue directly when reasonable, but should record that the fallback occurred.

---

## Delegated-task completion gate

Before producing the final answer for a delegated task, confirm that:

- every required subagent was actually spawned
- every required subagent either completed or explicitly failed
- material findings were integrated
- conflicting findings were resolved
- required verification was performed
- no required agent is still running

Do not finish while required subagents are still running.

Do not claim delegation occurred unless the `Agent` tool was actually called successfully.

---

## Final verification

Before claiming completion, the root should:

1. inspect the final diff
2. confirm the requested behavior is actually implemented
3. check material reviewer findings
4. run or confirm the highest-value tests
5. verify that delegated results were integrated correctly
6. state any validation that could not be performed

For implementation tasks, prefer checking:

- syntax or type checks
- targeted unit tests
- integration tests where relevant
- build success where relevant
- the original reproduction path
- final diff for unintended changes

---

## User-facing behavior

Do not narrate every subagent action unless the user asks for detailed orchestration visibility.

The final answer should focus on:

- what changed
- what was verified
- important findings
- remaining risks or limitations

When useful, briefly mention which agents contributed.

If the user explicitly asks to see delegation, report:

- subagent name
- model
- assigned task
- completion status

Do not claim a Haiku 5.5 agent was used unless a successful `Agent` call used `subagent_type` set to `explorer`, `worker`, `tester`, or `researcher` without a `model` argument, since those role files pin `claude-haiku-5-5`. The root cannot read subagent transcripts in-session. To confirm the model, the user can run `/tasks`.
