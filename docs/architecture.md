# Blue Ant V1 architecture notes

## First vertical slice

The bootstrap implements only deterministic primitives:

- typed task and worker-template models;
- task registration and dependency readiness;
- bounded retry state transitions;
- a fail-closed policy gateway for sensitive actions;
- a simple resource admission budget.

It does **not** yet execute arbitrary commands, create operating-system processes, call AI models, inspect device resources, or modify other projects.

## Reuse evaluation

### CrewAI
Evaluate its Flows and Crew abstractions for optional role-based delegation. Keep Blue Ant's policy gateway and task ledger authoritative. Do not allow framework agents to bypass approval checks.

### LangGraph
Evaluate only if durable graph state, resumability, or complex branching is needed beyond the simpler controller. Do not add both CrewAI and LangGraph to the same runtime without benchmark evidence.

### OpenHands SDK
Defer until the core can provide isolated workspaces, constrained tools, timeouts, and auditable execution. Treat it as an optional developer-worker adapter, not as the master controller.

## Next milestones

1. Add deterministic scheduler with bounded concurrency and dependency-aware dispatch.
2. Add append-only audit events and persistence.
3. Add isolated workspace/branch adapter.
4. Benchmark CrewAI compatibility and dependency footprint on Python 3.12.
5. Add integration only if it reduces code and passes security/compatibility tests.
