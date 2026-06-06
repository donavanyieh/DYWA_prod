# Initial Parallel Build Spec

## Goal

Build the smallest end-to-end adaptive healing engine that proves the four workstreams can integrate through strict contracts.

This first build should be contract-complete and demoable, but intentionally small.

## Minimal System

### Shopping App

Required features:

- product list,
- product detail,
- cart,
- quantity update,
- checkout,
- order confirmation,
- Stage 0 reset.

Required planted bugs:

- At least one realistic frontend or backend behavior bug.
- At least one bug discoverable through normal user flow.

Rules:

- Do not expose planted bug IDs to persona agents, verifier, or fixing agent.
- Expected behavior must be documented in tests or app behavior spec.
- Reset must restore the buggy state.

### Persona Agents

Required features:

- One persona config.
- Playwright-controlled browser.
- Screenshot capture.
- Configurable OpenAI model observation adapter in live mode.
- Structured bug report output.
- Transcript event output for every major action.

Minimum persona:

```text
Budget buyer trying to find a product, add it to cart, adjust quantity, and checkout.
```

### Verifier

Required features:

- Accept `BugReportV1`.
- Compare against existing reports.
- Use evidence, expected behavior, and model reasoning.
- Emit `VerifierDecisionV1`.
- Validate fixture reports through the contract suite.

Minimum classifications:

- `confirmed`
- `duplicate`
- `invalid`
- `needs_more_evidence`

### Fixing Agent

Required features:

- Accept `FixTaskV1`.
- Create sandbox copy.
- Inspect code and tests.
- Apply patch.
- Run tests.
- Emit `FixResultV1`.
- Promote only when tests pass.

The first build may use a narrow local repository layout, but the agent must not hardcode bug-specific fixes.

### Orchestrator And Dashboard

Required features:

- One command to start a run.
- Stage 0 reset.
- Component status tracking.
- Transcript JSONL store.
- Dashboard run bundle.
- Simple dashboard timeline.
- Artifact links for screenshots, patches, and test reports.

## First End-To-End Scenario

1. Orchestrator creates `run_id`.
2. Orchestrator resets app to buggy state.
3. Shopping app starts locally.
4. Persona explores cart flow.
5. Persona observes a suspected cart issue.
6. Persona emits bug report and transcript events.
7. Verifier confirms the issue.
8. Orchestrator creates fix task.
9. Fixing agent patches in sandbox.
10. Fixing agent runs tests.
11. Passing patch is promoted.
12. Dashboard shows the full story.

## Owner Deliverables

### Owner 1: Shopping App

Deliver:

- `app/main.py`
- frontend assets,
- app tests,
- reset implementation,
- expected behavior notes,
- seeded buggy state.

Done when:

- app runs locally,
- reset works,
- tests encode intended behavior,
- persona can navigate core flow.

### Owner 2: Persona Agents

Deliver:

- persona runner,
- persona config,
- screenshot capture,
- transcript writer,
- bug report writer,
- Configurable OpenAI model observation adapter.

Done when:

- agent can run against app URL,
- emits valid transcript events,
- emits valid bug report,
- works in live model-backed mode.

### Owner 3: Fixing Agent

Deliver:

- fix task consumer,
- sandbox manager,
- patch loop,
- test runner,
- fix result writer,
- promotion gate.

Done when:

- accepts fixture fix task,
- runs in sandbox,
- emits valid fix result,
- refuses promotion if tests fail.

### Owner 4: Orchestrator, Verifier, Dashboard

Deliver:

- run coordinator,
- verifier,
- dedupe store,
- transcript store,
- dashboard bundle builder,
- simple dashboard.

Done when:

- live smoke end-to-end run works,
- live persona report reaches verifier,
- confirmed report becomes fix task,
- dashboard renders transcript events directly.

## Acceptance Gates

The initial build is complete only when:

- `pytest` passes.
- Contract validation passes.
- Live smoke end-to-end run passes.
- Live end-to-end run passes for at least one confirmed bug.
- Dashboard shows persona, verifier, and fixing agent events.
- Reset can rerun the demo from the buggy state.

## Implementation Guardrails

- No private payload extensions except inside `metadata`.
- No component reads another component's internal files except through documented artifacts.
- No bug-specific hardcoding in persona, verifier, or fixing agent.
- No promotion without tests.
- No silent contract validation failures.
- No dashboard-only transcript transformation.
