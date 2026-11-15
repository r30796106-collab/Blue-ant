# Blue Ant

Blue Ant is an independent, resource-aware multi-agent workforce for coordinating software and research projects.

## Project direction

Blue Ant is developed independently before any integration with ELON, Trading Automation, StoryVerseAI/VoiceStudio, or FISHERMAN.

The first release prioritizes a reliable deterministic core. AI model integrations are optional adapters and are not required for task scheduling, policy enforcement, state transitions, or test execution.

## Reuse-first strategy

Prefer adopting and adapting mature open-source components over rebuilding equivalent functionality:

- **CrewAI**: evaluate for role-based crews, delegation, and flows.
- **LangGraph**: evaluate as an alternative workflow runtime where durable state/checkpointing is needed. Avoid running two orchestration frameworks in the same execution path without a demonstrated need.
- **OpenHands Software Agent SDK**: evaluate later as an optional developer-worker adapter, subject to isolation, dependency, and Android/Ubuntu compatibility checks.

No third-party framework is considered adopted until its license, supported Python versions, transitive dependencies, security posture, and runtime footprint have been reviewed.

## V1 architecture

1. **Master controller** — accepts projects and tasks, tracks state, and coordinates wings.
2. **Wings** — isolated project/team configurations (ELON, Trading, Animation, FISHERMAN, and shared QA/Optimization).
3. **Worker registry and templates** — create bounded worker instances from reviewed templates; no uncontrolled self-replication.
4. **Scheduler** — dependency-aware queue, bounded concurrency, retries, and resource-aware admission.
5. **Workspace isolation** — separate worktrees/branches or directories per task; prevent conflicting writes.
6. **Policy gateway** — explicit allowlists, approvals for destructive/high-impact actions, and deny-by-default external side effects.
7. **Verification** — tests, review results, audit events, and evidence-backed completion reports.

## Safety boundaries

- No real-money trading or automatic order execution.
- Security testing only against explicitly authorized targets and scopes.
- No unrestricted shell, credential access, destructive deletion, deployment, or large downloads without explicit policy approval.
- Workers cannot change their own permissions or bypass the policy gateway.
- Every task has resource limits, timeout, retry limit, and auditable state transitions.
- AI integrations remain optional and paused by default.

## Development principles

- Python-first, modular, deterministic core.
- Target Python 3.12 initially; validate on Ubuntu/Termux before claiming Android compatibility.
- Prefer small, independently testable milestones.
- Keep the default branch stable; develop on feature branches and merge through reviewed pull requests.
- Never claim tests ran unless a real execution environment reports the result.

## Status

Repository bootstrap. No implementation or test results are claimed yet.
