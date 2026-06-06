# Integration Plan

## Integration Philosophy

Each team builds independently against shared contracts and live runner interfaces. Integration succeeds when all live components exchange valid payloads without changing payload shape, field names, enum values, or dashboard expectations.

## Local Development Setup

Each owner should be able to run:

```bash
pytest
python -m shared.contracts.validate fixtures/
python -m orchestrator.run --mode live
```

The live end-to-end run should be:

```bash
python -m orchestrator.run --mode live
```

## Shared Fixtures

Create fixtures for:

- valid persona config,
- valid transcript event,
- valid bug report,
- valid verifier decision,
- valid fix task,
- valid fix result,
- invalid payload examples.

Fixtures live under:

```text
fixtures/contracts/
```

Every component must validate against these fixtures. Fixtures are for contract validation only, not mock execution.

## Live Runner Strategy

All runtime paths use live runners. The first build should be small enough that live runs are affordable and observable.

Owner 1 live runner:

- starts the FastAPI app,
- serves seeded buggy state,
- exposes Stage 0 reset.

Owner 2 live runner:

- drives Playwright against the live app,
- uses the configured OpenAI model to interpret screenshots and page context,
- emits valid exploration transcript and bug reports.

Owner 3 live runner:

- accepts a valid fix task,
- patches in a sandbox,
- runs tests,
- emits a valid fix result.

Owner 4 live runner:

- orchestrates real components,
- uses the configured OpenAI model for verifier classification,
- stores live transcript events.

Contract fixtures remain deterministic. Runtime behavior is live.

## Contract Testing

Each component must include:

- inbound schema validation tests,
- outbound schema validation tests,
- rejection tests for invalid enum values,
- rejection tests for missing required fields,
- fixture compatibility tests.
- live smoke tests with small action and time budgets.

Contract validation is a release gate. A component is not integration-ready until contract tests pass.

## End-To-End Test Flow

1. Run Stage 0 reset.
2. Start shopping app.
3. Start dashboard.
4. Launch persona agent with `PersonaConfigV1`.
5. Store emitted transcript events.
6. Store emitted bug reports.
7. Verifier consumes bug reports.
8. Confirmed reports become `FixTaskV1`.
9. Fixing agent consumes fix tasks.
10. Fixing agent emits fix transcript and `FixResultV1`.
11. Orchestrator runs integration checks.
12. Dashboard displays final run bundle.

## Branch And Merge Strategy

- Default branch: `main`
- Feature branches use `codex/<workstream>-<short-description>`
- Contract changes require review from all owners.
- Component-only changes require owner review and passing contract tests.
- Fixing agent promotion to `main.py` occurs only inside the sandboxed demo workflow and only after tests pass.

## Contract Change Process

1. Propose schema change in `specs/data_contracts.md`.
2. Update shared model implementation.
3. Update fixtures.
4. Update all affected component tests.
5. Run full contract suite.
6. Get approval from all owners.

No owner should introduce private extensions outside `metadata`.

## Integration Checkpoints

Checkpoint A: Dashboard renders fixture transcript.

Checkpoint B: Orchestrator live smoke run completes.

Checkpoint C: Persona live exploration emits valid reports.

Checkpoint D: Verifier live triage emits valid decisions.

Checkpoint E: Fixing agent consumes valid fix task and emits valid result.

Checkpoint F: Full live reset-explore-triage-fix-test-dashboard loop succeeds.

## Drift Detection

Add a validation step to CI or local preflight:

```bash
python -m shared.contracts.validate artifacts/latest_run
```

This should fail if:

- required fields are missing,
- unknown fields appear outside `metadata`,
- enums drift,
- timestamps are invalid,
- artifact references point to missing files,
- dashboard bundle cannot be built.
