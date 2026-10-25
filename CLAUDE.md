<!-- claude-orchestrator:start -->
## Claude Code orchestration

For complex coding tasks, use the `claude-orchestrator` skill (`/claude-orchestrator`) when its trigger conditions match.

The root agent owns architecture, decomposition, integration, and final verification.
Prefer specialized subagents (`explorer`, `worker`, `tester`, `reviewer`, `researcher`) for bounded exploration, implementation, testing, review, and technical research.

Do not delegate trivial work merely for parallelism.
Do not let multiple implementation agents edit the same files without explicit ownership boundaries.
User instructions always take precedence over this orchestration policy.
<!-- claude-orchestrator:end -->
