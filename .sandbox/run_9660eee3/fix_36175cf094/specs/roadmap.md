# Adaptive Healing Engine Roadmap

## Milestone 0: Contract Freeze

Goal: Establish the shared vocabulary before implementation.

Required outputs:

- `data_contracts.md` accepted by all owners.
- JSON Schema or Pydantic models implemented in a shared package.
- Golden fixture payloads for each component.
- Contract validation command that can run in CI or locally.

Acceptance criteria:

- Every owner can validate sample input and output for their component.
- Unknown fields are either rejected or explicitly allowed by schema.
- Enum values are fixed and documented.
- Dashboard can render contract fixture transcripts and live runner transcripts.

## Milestone 1: Parallel Skeletons

Goal: Each owner builds a minimal component that satisfies contracts.

Owner 1 delivers:

- FastAPI app with simple product listing, cart, checkout, and order confirmation.
- Stage 0 reset endpoint or command.
- Initial planted bugs.
- Minimal tests.

Owner 2 delivers:

- One persona runner using Playwright.
- Screenshot artifact capture.
- Configurable OpenAI model observation adapter.
- Valid `BugReportV1` and `TranscriptEventV1` outputs.

Owner 3 delivers:

- Fix task consumer.
- Sandbox copy workflow.
- Test runner integration.
- Patch transcript output.
- Live model-backed patch loop for integration testing.

Owner 4 delivers:

- Orchestrator run loop.
- Configurable OpenAI model verifier adapter.
- Dedupe store.
- Transcript event store.
- Dashboard reading transcript JSON.

Acceptance criteria:

- All skeletons run independently with contract fixtures and live runner commands.
- All emitted payloads validate.
- Orchestrator can run end-to-end using live runners.

## Milestone 2: First Live End-To-End Loop

Goal: Prove the actual workflow using live runners.

Flow:

1. Reset app to buggy state.
2. Start app.
3. Launch persona agent.
4. Collect suspected bug report.
5. Verifier triages report.
6. Confirmed bug becomes fix task.
7. Fixing agent patches in sandbox.
8. Tests pass.
9. Patch is promoted to `main.py`.
10. Dashboard shows the full run.

Acceptance criteria:

- No hardcoded bug IDs or fix paths in persona, verifier, or fixing agent.
- The same transcript JSON drives dashboard display.
- Failure states are visible and typed.
- Integration run can be repeated from reset.

## Milestone 3: Reliability And Evidence

Goal: Make the demo robust.

Add:

- Multiple personas.
- More planted bugs.
- Reproduction evidence fields.
- Screenshot gallery in dashboard.
- Retry policy for flaky exploration.
- Duplicate clustering.
- Contract drift checks.

Acceptance criteria:

- Duplicate reports are grouped.
- Invalid reports are visible but not fixed.
- The fixing agent records failed attempts clearly.
- Tests prevent known fixed bugs from returning.

## Milestone 4: Demo Polish

Goal: Make the system easy to present.

Add:

- One-command demo runner.
- Seeded demo mode.
- Dashboard timeline.
- Owner health panel.
- Run summary.
- Exportable transcript bundle.

Acceptance criteria:

- Demo can be reset and replayed.
- A non-developer can follow discovery, triage, fix, and verification.
- All artifacts are linked from dashboard events.

## Parallel Development Rules

- Owners must not change shared contracts without a contract review.
- Components must support fixture-based contract validation.
- Components must fail fast on invalid payloads.
- Dashboard must consume transcript events exactly as emitted.
- Live runners must use the same contracts as their fixtures.
- Integration checkpoints happen at the end of every milestone.
