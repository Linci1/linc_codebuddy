# CodeBuddy V2 Release Readiness

## Scope

This release candidate contains the local V2.0-V2.4 engineering foundation:

- stable work item and task identity;
- state migration, recovery, and atomic persistence;
- adaptive L0-L3 governance;
- repository-backed project, change, phase, and gate records;
- acceptance evidence, drift detection, and release readiness;
- read-only GitLab reference synchronization with conflict protection;
- workspace status and pilot evaluation.

Real GitLab API access, external writes, and a resident multi-agent runtime are not part of this release candidate.

## Verification

- Unit and integration suite: 41 tests passing.
- Repository quick validation: passing.
- Python compilation: passing.
- Git diff whitespace validation: passing.
- Real-project pilot: completed; V3 decision is no-go until repeated orchestration bottlenecks are observed.

## Release Boundaries

- `.codex/linc_codebuddy/project.yaml`, changes, and evidence are repository-backed lifecycle records and should be reviewed with the code.
- `.codex/linc_codebuddy/state.json` contains machine-local runtime state and must not be committed.
- `.playwright-cli/`, Python bytecode, and operating-system metadata are local artifacts and must not be committed.
- GitLab synchronization remains reference-only. Applying a plan changes local change metadata, not GitLab.
- No release transition, commit, tag, push, or remote migration is implied by verification readiness.

## Proposed Commit Groups

1. State identity, migration, task synchronization, and ship safety.
2. Adaptive governance and lifecycle records.
3. Evidence, verification, drift, and GitLab reference synchronization.
4. MCP/workspace integration, documentation, tests, and pilot records.

Before creating commits, review the complete dirty worktree because it includes the full V2 series and earlier local changes.
