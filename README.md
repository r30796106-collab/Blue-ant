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


## Parallel multi-project workforce (v1)

The workforce can run multiple specialist tasks at the same time against one repository, and can coordinate tasks across several registered repositories in one local invocation. Each task receives a unique workspace path; built-in v1 specialists remain read-only.

### Local use

Install Blue Ant, then provide one or more checked-out repositories. Repeat `--project` for every repository:

```bash
python -m pip install -e ".[dev]"
blue-ant-workforce \
  --project elon=/path/to/ELON \
  --project trading=/path/to/ai_crypto_bot \
  --project animation=/path/to/StoryVerseAI \
  --roles repo_analyst,test_auditor,docs_auditor,safety_auditor \
  --max-workers 4 \
  --output blue-ant-workforce-report.json
```

Every project receives one task per selected role. Tasks across the same repository and different repositories share one bounded worker pool, so they can run concurrently without exceeding `--max-workers`. A worker failure is recorded per task and does not discard successful results from other tasks.

### GitHub Actions: multiple repositories

Open **Actions → Blue Ant Multi-Repository Workforce → Run workflow** and provide a JSON array. Each matrix entry checks out one public repository and runs its specialist tasks concurrently; up to four repositories run at once:

```json
[
  {"project_id":"elon","repository":"owner/ELON","ref":"main"},
  {"project_id":"trading","repository":"owner/ai_crypto_bot","ref":"main"},
  {"project_id":"animation","repository":"owner/StoryVerseAI","ref":"main"}
]
```

The workflow uses read-only checkout permissions and does not persist repository credentials. It is intended for public repositories. Private repositories require a separately configured least-privilege credential and are not enabled by this workflow.

### v1 boundaries

- Current workers are repository analysts/auditors, not autonomous code editors.
- No shell execution, package installation, project-code execution, deployment, or real-money trading.
- Task workspaces are separated directories, not OS-level sandboxes.
- Parallelism is bounded (1–16 workers); the GitHub matrix runs at most four repositories concurrently.
- Patch generation, approval, application, and post-change verification are the next developer-worker milestone.

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

The core, sub-bot fleet, project registry/workspaces, and approved patch pipeline have passed GitHub Actions on Python 3.12. The patch CLI is covered by CI in the current pull request.


## Approved coding-worker patch pipeline (v2 foundation)

A coding worker can prepare a complete file-change proposal for a dedicated,
disposable project workspace. Blue Ant validates every path and expected
SHA-256 before writing anything, rejects traversal and symlinks, and requires
an explicit approval flag before applying changes. File creation and
replacement are supported; deletion, shell execution, package installation,
test execution, deployment, and automatic GitHub pushes are not.

```python
from blue_ant import FileChange, PatchProposal, apply_patch_proposal, sha256_text

proposal = PatchProposal(
    proposal_id="change-001",
    project_id="demo",
    task_id="implement-feature",
    changes=(
        FileChange("src/example.py", "print('updated')\\n", sha256_text("print('old')\\n")),
    ),
)
# Apply only after a human has reviewed and approved the proposal.
result = apply_patch_proposal("/path/to/disposable/workspace", proposal, approved=True)
```

The patch engine is a guarded workspace writer, not an OS sandbox or a
multi-file atomic transaction. Run project tests in a separately isolated CI
runner after applying a proposal. A future GitHub adapter can turn verified
workspace changes into branch commits and pull requests.


### Review and apply a patch proposal from the command line

A proposal is JSON data with `proposal_id`, `project_id`, `task_id`, and a
`changes` array. Each change contains `path`, complete UTF-8 `content`, and
`expected_sha256` (use `null` only when creating a new file). Review first:

```bash
blue-ant-patch --workspace /path/to/disposable/workspace --proposal proposal.json
```

The command is dry-run by default and does not write files. After a human has
reviewed the paths and contents, apply explicitly:

```bash
blue-ant-patch --workspace /path/to/disposable/workspace --proposal proposal.json --approve
```

This CLI does not execute project code, run tests, create Git branches, or push
to GitHub. Verify applied changes in a separate CI job before proposing a merge.


## GitHub instruction → worker → result cycle (V1)

The **Blue Ant Instruction Worker** workflow accepts a JSON array of bounded instructions and runs up to four public-repository jobs concurrently. Each instruction names a project, repository/ref, and one approved specialist role. Every job publishes an instruction manifest and structured workforce report as a downloadable artifact.

Open **Actions → Blue Ant Instruction Worker → Run workflow** and provide:

```json
[
  {
    "instruction_id": "inspect-001",
    "project_id": "blue-ant",
    "repository": "owner/repository",
    "ref": "main",
    "worker_role": "repo_analyst",
    "task": "Inventory files and summarize repository structure"
  }
]
```

Allowed roles: `repo_analyst`, `test_auditor`, `docs_auditor`, and `safety_auditor`. Results are published as `blue-ant-result-<instruction_id>` artifacts. A controller can review those results and submit the next instruction in a subsequent run.

V1 boundary: task text is context metadata, not executable code. Specialists perform only fixed read-only audit routines. This workflow does not edit target repositories, run their test suites, create branches/PRs, or call ChatGPT automatically. The controller reviews the artifact and decides the next step. Public repositories only by default.


## Human-gated GitHub patch worker (V1)

The **Blue Ant Approved Patch Worker** workflow accepts a strict JSON
`PatchProposal`, checks out the selected public repository into a disposable
GitHub Actions workspace, and runs the existing hash-checked patch engine.

1. Run **Actions → Blue Ant Approved Patch Worker → Run workflow**.
2. Supply the public repository, target ref, project ID, and complete patch JSON.
3. Keep `apply_approved=false` to validate and dry-run the proposal.
4. Set `apply_approved=true` only after reviewing the proposal and explicitly
   approving its application.
5. Download the resulting artifact to inspect the proposal, status, and diff.

The worker validates the proposal schema, project ID, change count, content
size, and expected SHA-256 values. The patch engine rejects traversal paths,
reserved paths, symlinks, duplicate paths, stale hashes, and implicit
overwrites. It supports file creation/replacement only.

**Important V1 boundary:** applying a patch changes only the disposable
workflow checkout. The workflow has read-only GitHub permissions, does not
push commits or open PRs, and does not execute target code or tests. A human
must review the artifact and decide whether to apply the resulting changes
through a separate approved GitHub operation. This is a controlled patch
executor, not yet an autonomous code-generating agent.


## ChatGPT ↔ GitHub issue worker feedback loop (V1)

The **Blue Ant Issue-Driven Worker Loop** connects a controller to GitHub
without storing an LLM API key in the repository. A controller (including
ChatGPT when operating through an authorized GitHub connection) can create a
`[blue-ant]` issue containing one strict JSON instruction. GitHub Actions
runs the requested fixed specialist and posts the structured result back as
an issue comment. The controller reads that comment, decides the next step,
and opens the next instruction issue. Multiple issues can run concurrently.

Example issue body:

```json
{
  "instruction_id": "inspect-001",
  "project_id": "blue-ant",
  "repository": "r30796106-collab/Blue-ant",
  "ref": "main",
  "worker_role": "repo_analyst",
  "task": "Inspect the repository structure and report key components"
}
```

Only issues opened by the repository owner account with a title beginning
`[blue-ant]` trigger the worker. Only public repositories under
`r30796106-collab` and the four built-in specialist roles are accepted.
The task field is controller context; it is not interpreted as code or as
arbitrary shell instructions. Workers remain read-only and do not execute
target tests or edit project files.

This creates the V1 **instruction → worker → result comment → next instruction**
loop. The human/controller remains responsible for reviewing results and
deciding when to use the separately approval-gated patch worker.


## Issue-driven human-gated patch worker

A controller can submit a structured patch proposal through a GitHub issue titled `[blue-ant-patch] ...`. The issue body must be JSON with exactly these fields: `target_repository`, `target_ref`, `project_id`, `proposal`, and `apply_approved`. The proposal uses the same strict `PatchProposal` schema as the CLI.

- Set `apply_approved: false` for validation/dry-run (default recommendation).
- Set `apply_approved: true` only when a human has reviewed and explicitly approved the exact proposal.
- The workflow runs the existing hash/path/symlink-guarded patch engine in a disposable checkout and uploads the review, diff, status, and proposal artifacts.
- The result is posted back to the controlling issue.

Only issues opened by `r30796106-collab` trigger this worker, and only public repositories under that account are accepted. The workflow has read-only repository permissions, does not persist checkout credentials, and never commits, pushes, opens a PR, or merges. Even an approved apply affects only the temporary runner checkout. It does not execute target project code or tests.


## Multi-repository approved coding worker

The issue-driven coding worker accepts an optional `target_repository` field. If omitted, it targets Blue Ant itself (backward compatible). If supplied, the value must name a public repository owned by `r30796106-collab`. The worker checks out that repository/ref, applies the same explicitly approved hash-checked patch, and opens a PR in that target repository. It never merges.

Same-repository work uses the workflow's narrowly scoped `GITHUB_TOKEN`. Cross-repository writes require a repository Actions secret named `BLUE_ANT_WORKER_TOKEN` containing a fine-grained token limited to the intended target repositories, with **Contents: Read and write** and **Pull requests: Read and write** permissions. Do not use a personal account-wide token. Without this secret, cross-repository instructions fail before checkout or writes.

Example issue body (all fields are required except `target_repository`):

```json
{
  "target_repository": "r30796106-collab/ELON",
  "target_ref": "master",
  "project_id": "elon",
  "proposal": {
    "proposal_id": "elon-change-001",
    "project_id": "elon",
    "task_id": "update-module",
    "changes": [
      {
        "path": "README.md",
        "content": "Complete replacement file contents\\n",
        "expected_sha256": "replace-with-current-lowercase-sha256"
      }
    ]
  },
  "apply_approved": true
}
```

After opening the target PR, Blue Ant dispatches its own test suite and the read-only specialist review against the target repository/ref. The Blue Ant test suite verifies Blue Ant's worker code; the specialist report audits the target repository and does not execute its tests. Target-project test execution remains a separate CI capability and is not claimed by this workflow. Private repositories are not supported by this workflow.

## Deterministic development-plan generator

The blue-ant-plan command combines a bounded audit-loop JSON report with an optional target Python test result JSON report and emits a deterministic, human-reviewable task plan:

    blue-ant-plan --project-id elon --audit-report elon-audit-loop.json --test-report elon-target-tests.json --output elon-development-plan.json

The generator validates report versions, project identity, approved specialist roles, finding severity/path fields, target owner/ref, and the supported test profile. It converts findings and failed test status into bounded review tasks. A passing test report is tied to its exact target repository ref.

Safety boundary: plans contain recommendations only. They never contain patch contents or executable commands; apply_approved is always false and patch_proposal is always null. A human must verify findings, prepare/review a separate hash-checked patch proposal, and explicitly approve that proposal through the existing coding worker. Safety-auditor findings are always routed to human security review rather than automatic patch generation.
## Controlled patch-proposal builder

The blue-ant-propose command packages externally supplied replacement content for exactly one eligible development-plan task. It reads the target workspace, verifies that the task names one existing regular file, requires the proposed path to match that exact path, and calculates the current SHA-256 itself.

    blue-ant-propose --workspace ./target --plan development-plan.json --task-id review-finding-1 --change change.json --output proposal.json

The change JSON contains exactly path and content. The output uses the existing strict patch-proposal schema and can be submitted to the existing issue-approved PR worker for explicit human approval.

Safety boundary: this builder never writes to the target workspace, creates files, generates code, runs commands, or approves/applies patches. It rejects safety-review, informational, test-result, missing-file, symlinked, and multi-file tasks. Only a human-reviewed audit finding tied to one concrete existing file is eligible. The target repository remains unchanged while the proposal is built.

[Blue Ant temporary smoke link](docs/__blue_ant_smoke_missing__.md)
