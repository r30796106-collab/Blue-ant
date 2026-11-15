# Blue Ant

Blue Ant is an independent, resource-aware multi-project workforce for coordinating software and research projects.

## Current milestone

The deterministic core provides a bounded task scheduler, deny-by-default action policy, append-only audit writer, resource-capacity policy, a read-only sub-bot fleet, and an explicit project registry with isolated workspace paths.

## First sub-bot fleet

Four built-in, read-only specialists can inspect a checked-out repository:

- **Repo Analyst** — inventories text files and file types.
- **Test Auditor** — locates conventional tests and CI workflows; does not execute project tests.
- **Docs Auditor** — checks for a project README.
- **Safety Auditor** — flags selected dynamic-execution and shell-invocation patterns for human review.

The fleet is created from fixed templates with a configurable hard limit (default four). It does not self-replicate, run shell commands, execute inspected project code, access credentials, or modify the target repository. Findings are heuristic and are not a security certification.

## Project registry and workspaces

Register each project explicitly before requesting its workspace:

```python
from blue_ant import ProjectRegistry

registry = ProjectRegistry(".blue-ant/workspaces")
registry.register("elon", "/path/to/ELON")
registry.register("trading", "/path/to/ai_crypto_bot")

elon_workspace = registry.workspace_for("elon", create=True)
trading_workspace = registry.workspace_for("trading", create=True)
```

The registry validates project IDs, rejects duplicate registrations and symlink source roots, and assigns one workspace directory per registered project. Workspace creation is opt-in, does not copy or modify source files, and rejects symlinked workspace directories. The current registry is in-memory; persistent configuration and actual worker execution isolation are later milestones. Separate directories alone are not an OS security sandbox.

### Run locally

Requires Python 3.12 or newer.

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
pytest
blue-ant-review --repo . --output blue-ant-report.json
```

### Run through GitHub Actions

Open **Actions → Blue Ant Sub-bot Review → Run workflow**. Optionally provide a public repository in `owner/name` format and a ref. The workflow checks out the target without persisting credentials, runs the four read-only specialists, and uploads a JSON report artifact.

The workflow currently uses the runner's default GitHub token and is intended for public targets. Private target repositories require an explicitly configured, least-privilege credential and are not enabled by default.

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

## Verification status

The core and first sub-bot fleet passed GitHub Actions on Python 3.12 (19 tests). The project registry/workspace milestone is under review in its own pull request; its tests must pass CI before it is considered verified.
