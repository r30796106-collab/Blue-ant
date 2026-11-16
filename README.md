# Blue Ant

Blue Ant is an independent, resource-aware multi-project workforce for coordinating software and research projects.

## Current milestone

The deterministic core provides a bounded task scheduler, deny-by-default action policy, tamper-evident append-only JSONL audit log with hash-chain verification, resource-capacity policy, a read-only sub-bot fleet, and an explicit project registry with isolated workspace paths.

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

The registry validates project IDs, rejects duplicate registrations and symlink source roots, and assigns one workspace directory per registered project. Workspace creation is opt-in, does not copy or modify source files, and rejects symlinked workspace directories. Separate directories alone are not an OS security sandbox.

By default, the registry remains in memory. To persist registrations across process restarts, provide an explicit JSON registry path:

```python
registry = ProjectRegistry(
    ".blue-ant/workspaces",
    registry_path=".blue-ant/projects.json",
)
registry.register("elon", "/path/to/ELON")
```

The versioned registry is written atomically with owner-only file permissions. On startup, stored project IDs and source directories are revalidated; missing, invalid, or symlinked registry/source paths are rejected. The file stores machine-local absolute source paths, so keep it local and do not commit it or share it between machines.

The `blue-ant-project` command provides the same operations from a terminal:

```bash
blue-ant-project register elon /path/to/ELON
blue-ant-project register trading /path/to/ai_crypto_bot
blue-ant-project list
blue-ant-project workspace elon
blue-ant-project workspace elon --create
```

Use `--registry PATH` and `--workspace-root PATH` before the subcommand to override the defaults. A workspace lookup is read-only; the directory is created only when `--create` is supplied.

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
  --audit-log .blue-ant/workforce-audit.jsonl \
  --output blue-ant-workforce-report.json
```

Every project receives one task per selected role. Tasks across the same repository and different repositories share one bounded worker pool, so they can run concurrently without exceeding `--max-workers`. A worker failure is recorded per task and does not discard successful results from other tasks. When `--audit-log PATH` is supplied, the workforce records task preparation, worker start/success/failure, and run completion in the tamper-evident hash-chained JSONL log. The chain is verified before and after the run; a pre-existing invalid log stops execution. The report includes the verification status.

By default, read-only specialists inspect the registered source directly. Add
`--snapshot-sources` to copy each project into its own task workspace before
inspection:

```bash
blue-ant-workforce \
  --project elon=/path/to/ELON \
  --roles repo_analyst,test_auditor,docs_auditor,safety_auditor \
  --max-workers 4 \
  --snapshot-sources \
  --output blue-ant-workforce-report.json
```

Snapshots are bounded to 5,000 files, 5 MB per file, and 50 MB total by
default. They exclude VCS, dependency, cache, build, and virtual-environment
directories, plus common credential files and private-key formats. Symlinks
and special files fail closed; copied files receive owner-only permissions.
The source project is never modified. A task snapshot is not an OS sandbox,
and the workspace is not automatically deleted or overwritten on reruns.

For read-only specialist fleets, add `--shared-snapshot-sources` alongside
`--snapshot-sources` to copy each registered project once and reuse that
private snapshot across its workers. The fixed specialists also build one
bounded in-memory text index from that shared snapshot and reuse it, avoiding
repeated directory walks and file reads. Every assignment still receives a
separate task workspace; workers only read the shared snapshot/index. The
shared snapshot is retained under the project workspace and is not overwritten
on a rerun. This option requires `--snapshot-sources`; the ChatGPT bridge uses
shared snapshots automatically when snapshot mode is requested.

For resource-aware concurrency on a constrained device, provide a CPU count
and available memory (MiB). Blue Ant then caps the worker pool using a
512 MiB default reserve and 256 MiB per-worker budget:

```bash
blue-ant-workforce \
  --project elon=/path/to/ELON \
  --max-workers 8 \
  --cpu-count 4 \
  --available-memory-mb 3072 \
  --snapshot-sources
```

Override the budgets with `--reserve-memory-mb` and
`--memory-per-worker-mb`. The JSON report records both requested and
effective worker counts and the capacity snapshot used. Capacity values can
be caller-supplied, or detected explicitly on Linux using standard-library
reads of `/proc/meminfo` and common cgroup v1/v2 limits. Detection is one-shot
and opt-in; it does not start monitoring or a daemon. Unsupported hosts or
missing `MemAvailable` data fail closed. For example:

```python
from blue_ant import ProjectRegistry, ResourcePolicy, ResourceSnapshot, Workforce

snapshot = ResourceSnapshot.detect()
workforce = Workforce(
    ProjectRegistry(".blue-ant/workspaces"),
    max_workers=8,
    resource_policy=ResourcePolicy(max_workers=8),
    resource_snapshot=snapshot,
)
```

The CLI continues to accept explicit CPU and memory values; it does not
silently probe the host.

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

The workflow also accepts a `snapshot_sources` boolean input. Set it to
`true` to make each specialist inspect its own bounded, private task snapshot
instead of reading the checkout directly. The same file-count, byte, symlink,
and credential-file exclusions apply; repositories exceeding the snapshot
limits fail closed.

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
4. Dependency-aware scheduler with hard limits of 16 workers, 256 tasks per run, and 10 attempts per task.
5. Separate workspaces/branches to prevent conflicting writes.
6. Deny-by-default policy gateway and human approval for high-impact actions.
7. Test-backed verification and append-only audit events.


## Tamper-evident audit log

The `AuditLog` appends JSONL events linked by SHA-256 hashes. Each record
contains the previous record hash and its own digest. `verify()` checks the
entire chain; POSIX file locks serialize independent writer instances and
processes. The writer rejects symlinked paths, reserves chain metadata, and
uses owner-only file permissions for new logs.

```python
from blue_ant import AuditLog

audit = AuditLog(".blue-ant/audit.jsonl")
audit.record("patch_proposal_approved", proposal_id="change-001")
result = audit.verify()
if not result.valid:
    raise RuntimeError(result.error)
```

This detects modified, missing, reordered, or malformed records when checked
against the existing chain. It is not a digital signature or external
tamper-proof storage: an attacker able to rewrite the entire log can rebuild
the chain. Back up or externally anchor important audit hashes.


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
globally atomic multi-file transaction. It limits proposals to 10 files, 1 MB
per file, and 2 MB combined; preserves existing file permission bits; creates
new files with owner-only permissions; and attempts atomic per-file rollback
if a later replacement fails. Use a dedicated disposable workspace that is
not concurrently modified by untrusted processes. Run project tests in a
separately isolated CI runner after applying a proposal.


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

When `--approve` is used, the CLI writes a hash-chained audit trail to
`<workspace>/.blue-ant/patch-audit.jsonl` by default. Override it with
`--audit-log PATH`. The CLI verifies the chain before and after applying;
if the log is invalid, it refuses to apply the proposal.

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

## Deterministic code preparation (human-reviewed drafts)

The `blue-ant-prepare` command creates complete replacement-file drafts for
a deliberately small set of mechanically verifiable documentation repairs:

- Close an unclosed Markdown fenced code block using the matching fence marker.
- Correct a broken relative README link only when exactly one existing target
  matches the intended path case-insensitively and the Markdown link occurs once.

Example:

```bash
blue-ant-prepare --workspace ./target --plan development-plan.json --output prepared-tasks.json
```

The command is read-only: it never changes the target workspace, executes target
code, installs dependencies, or approves a patch. Unsupported, ambiguous,
security-related, non-README, and oversized cases remain `manual_review`.
The audit-to-plan workflow can include a prepared full-file draft in a generated
coding-task issue, but `apply_approved` remains `false`. A human must verify
the finding, review or replace the complete content, and explicitly approve by
editing the issue as the repository owner. The existing worker then recalculates
the target file hash and opens a PR; it never merges or deploys.


## ChatGPT Control Bridge V1 (GitHub issue mailbox)

ChatGPT can submit a bounded command by creating an issue titled
`[blue-ant-bridge] <short description>` in this repository. Blue Ant validates
the exact JSON envelope, checks the owner identity, runs the selected fixed
read-only specialists against the named public repository/ref, generates a
deterministic review plan, uploads JSON artifacts, and posts a result comment
to the same issue. ChatGPT can read that comment and decide whether to submit
another command.

Example issue body (raw JSON; do not wrap it in Markdown fences):

```json
{
  "schema_version": 1,
  "command_id": "inspect-elon",
  "command": "audit_plan",
  "project_id": "elon",
  "repository": "r30796106-collab/Elon",
  "ref": "master",
  "roles": ["repo_analyst", "test_auditor", "docs_auditor", "safety_auditor"],
  "max_cycles": 4,
  "task": "Inspect repository health and prepare a review plan",
  "snapshot_sources": true
}
```

Bridge V1 supports only `audit_plan`, 1–4 unique approved roles, public
repositories owned by `r30796106-collab`, and a 16 KiB command limit. The task
is context metadata only; it is never executed as code or shell input. The
workflow has read-only target checkout permissions. It does not run target
tests, generate arbitrary code, modify files, approve/apply patches, merge PRs,
or deploy. Existing human-approved coding workflows remain separate.

The optional `snapshot_sources` field defaults to `false`. Set it to
`true` to make each selected specialist inspect its own bounded private
snapshot. Snapshots exclude common generated and credential-like paths, reject
symlinks, and fail closed above the 5,000-file / 50 MB limits. The controller
preserves this setting when continuing to the next pre-authorized role.
Private bridge snapshots are stored outside the uploaded `artifacts/` directory;
the workflow artifact contains JSON reports and the hash-chained event log,
not the copied project tree. The event log is copied from the private workspace
with owner-only permissions; the bridge comment reports its verification status.

**Important operating boundary:** this is a GitHub issue-based command/result
bridge, not a continuously running ChatGPT process or a direct ChatGPT API
connection. ChatGPT must be active/connected to submit the next command and
read the result. True unattended continuous control requires a separately
hosted controller and explicitly configured API credentials; that is not part
of V1.


### Parallel approved-task worker: required credential

The `Blue Ant Parallel Approved Task Bundle` workflow is fail-closed: it
requires a repository secret named `BLUE_ANT_WORKER_TOKEN` before it checks
out or writes to a target repository. It deliberately does not fall back to
the workflow's default `GITHUB_TOKEN`, which normally has access only to the
Blue Ant repository.

For a target repository such as `r30796106-collab/Elon`, configure the
secret in **Blue Ant → Settings → Secrets and variables → Actions**. The
fine-grained personal access token must be granted access to the exact target
repository and have **Contents: Read and write** and **Pull requests: Read
and write**. Keep the token private; never paste it into an issue, source
file, or chat. The workflow uses the token only for target checkout, branch
push, and PR creation. Review/test dispatch back to Blue Ant uses the
workflow-scoped GitHub token and its declared Actions permission.

A missing or mis-scoped token should fail before target checkout. A successful
credential preflight does not itself prove that GitHub accepted all write
operations; verify the complete flow with a disposable test proposal before
using real project changes.

Approved patch workflows retain their hash-chained audit trail separately from
the target repository: issue-driven and plan-linked PR workers upload
`target/.blue-ant/patch-audit.jsonl` as a 14-day artifact, while the disposable
patch-review worker copies the log into its existing result artifact. Logs
contain event metadata and changed paths, not patch contents; they are never
staged or committed to the target repository.

Before dispatching parallel workers, the workflow resolves the approved target
ref once and pins every isolated worker to that exact commit SHA. Each worker
checks that the target branch still points to the pinned commit before applying
the proposal and checks again before opening its PR. If the branch moves during
preparation, the worker fails closed instead of applying against a different
baseline or opening a stale PR. The PR body records the pinned base SHA.


The ChatGPT Bridge enables the workforce hash-chain audit automatically.
Its execution log is stored under the private
`.blue-ant-workspaces/<command-id>/` directory, outside uploaded report
artifacts. The bridge verifies the log before publishing its result and
includes the verification status, record count, and final hash in the JSON
audit report. A failed verification stops the bridge run.


Audit failure events record only the exception class, not the exception message.
This keeps arbitrary error details (which can contain local paths or secrets)
out of the persistent audit trail. The in-memory `WorkResult.error` remains
available to the caller for controlled diagnostics.

## Local event adapter (V3 prototype, no API)

The `blue-ant-bridge-event` command is a local, one-shot event adapter for
the existing read-only bridge runner. It consumes an explicitly supplied
JSON event file and invokes only the fixed bridge audit pipeline.

Create an event with exactly these fields:

```json
{
  "schema_version": 1,
  "event_id": "inspect-001",
  "event_type": "bridge.command",
  "command_id": "inspect-elon"
}
```

Run it with an already validated bridge command, a checked-out target, a
report directory, and an existing private state directory:

```bash
blue-ant-bridge-event \\
  --event event.json \\
  --command validated-command.json \\
  --target-path ./target \\
  --output-dir ./bridge-output \\
  --state-dir ./.blue-ant-event-state
```

The adapter validates a strict event schema, binds the event to the command
ID, and claims each event ID with an exclusive owner-only receipt. Replaying
the same event returns the prior status without running workers again; reusing
an ID with different content is rejected. A crash while processing leaves a
`processing` receipt and intentionally blocks automatic replay (at-most-once,
fail-closed semantics). Inspect that receipt before any operator-directed
recovery.

This is deliberately **not** a background daemon, webhook, network listener,
ChatGPT API integration, or unattended controller. The caller must provide
the event and invoke the command. It has no credentials, shell execution,
patch approval/application, GitHub writes, merge, or deployment capability.
The bridge runner continues to inspect the target read-only.
