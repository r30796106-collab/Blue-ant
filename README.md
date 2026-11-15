# Blue Ant

Blue Ant is an independent, resource-aware multi-project workforce for coordinating software and research projects.

## Current milestone

The first implementation milestone is a deterministic Python core that can execute independent tasks concurrently, respect dependencies, bound retries, enforce an action policy, and write an audit trail.

## Reuse-first strategy

Prefer mature open-source components over rebuilding equivalent functionality:

- **CrewAI** is the first candidate for role-based crews and agent delegation. It will be adopted only after its license, Python support, dependencies, security posture, and runtime footprint are verified.
- **LangGraph** is an alternative workflow runtime for stateful orchestration/checkpointing. Avoid running two orchestration frameworks in one execution path without a demonstrated need.
- **OpenHands Software Agent SDK** is a later optional developer-worker adapter, subject to isolation and compatibility checks.

The deterministic core does not require an LLM or paid API. Third-party frameworks remain optional until a tested integration is justified.

## Architecture direction

1. Master controller and project/task registry.
2. Isolated project wings: ELON, Trading, Animation, FISHERMAN, and shared QA/Optimization.
3. Bounded worker templates; no uncontrolled self-replication.
4. Dependency-aware scheduler with bounded concurrency and retries.
5. Separate workspaces/branches to prevent conflicting writes.
6. Deny-by-default policy gateway and human approval for high-impact actions.
7. Test-backed verification and append-only audit events.

## Safety boundaries

- No real-money trading or automatic order execution.
- Security testing only against explicitly authorized targets and scopes.
- No unrestricted shell, credential access, destructive deletion, or deployment.
- Workers cannot change their own permissions or bypass policy.
- AI integrations are optional and paused by default.

## Development

Requires Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
```

The scheduler currently uses a bounded thread pool for local callable tasks. This is suitable for proving I/O-friendly concurrency; CPU-heavy workloads need a separately bounded process adapter and platform-specific validation.

## Test status

Tests are committed as a suite but have not been executed by this GitHub connector. Do not treat committed tests as passing until CI or a real Python environment reports the result.
