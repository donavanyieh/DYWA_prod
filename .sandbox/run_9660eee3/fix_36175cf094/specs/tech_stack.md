# Technical Stack

## Runtime

- Language: Python 3.11+
- Backend: FastAPI
- Frontend: Plain HTML, CSS, and JavaScript for the first build
- Browser automation: Playwright
- Validation: Pydantic v2 plus generated JSON Schema
- Testing: pytest, pytest-asyncio, Playwright test helpers
- Dashboard: FastAPI-served HTML/JS or lightweight React only if needed
- Storage: local JSONL transcript store for first build
- Model provider: configurable OpenAI model for all AI-driven persona, verifier, and fixing workflows; GPT-5 is the default

## Repository Shape

Recommended structure:

```text
app/
  main.py
  routes/
  services/
  static/
  templates/
  tests/
agents/
  personas/
  fixing/
orchestrator/
  verifier/
  dashboard/
shared/
  contracts/
  validation/
  artifacts/
specs/
  mission.md
  roadmap.md
  tech_stack.md
  data_contracts.md
  integration_plan.md
  initial_parallel_build_spec.md
```

## Shopping App

FastAPI serves:

- product catalog,
- product details,
- search,
- cart,
- checkout,
- order confirmation,
- static frontend assets,
- reset endpoint or command for Stage 0.

The app should include a small test suite that encodes expected behavior. Planted bugs should violate expected behavior but remain realistic.

## Persona Agent Runtime

Persona agents run as separate processes:

```text
PersonaConfigV1 -> Playwright actions -> screenshots -> AI observation -> BugReportV1 + TranscriptEventV1
```

Each persona has:

- goal,
- behavioral traits,
- max runtime,
- action budget,
- allowed app base URL,
- artifact output directory.
- OpenAI model configuration.

The agent selects actions based on current page state, persona goal, and model interpretation. It must not know planted bug IDs.

## Verifier

The verifier receives `VerifierInputV1` and returns `VerifierDecisionV1`.

It uses:

- report evidence,
- screenshots,
- transcript events,
- expected app behavior,
- existing confirmed bugs,
- Model reasoning.

It must classify reports as:

- `confirmed`,
- `duplicate`,
- `invalid`,
- `needs_more_evidence`.

## Fixing Agent

The fixing agent receives `FixTaskV1`.

It must:

- create or reuse an isolated sandbox copy,
- inspect source and tests,
- reproduce when possible,
- modify code,
- add or update tests when appropriate,
- run tests,
- emit `FixResultV1` and `TranscriptEventV1`.

Promotion to `main.py` is allowed only when:

- tests pass,
- changed files are scoped to the fix,
- contract validation passes,
- verifier or orchestrator accepts the fix result.

## Orchestrator

The orchestrator coordinates:

- Stage 0 reset,
- service startup,
- persona runs,
- report collection,
- verifier calls,
- fix task creation,
- fixing agent calls,
- integration tests,
- transcript persistence,
- dashboard refresh.

It is the only component that owns global run state.

## Dashboard

The dashboard reads transcript JSON or JSONL directly.

It should display:

- run status,
- timeline,
- persona activity,
- screenshots,
- suspected bugs,
- verifier decisions,
- fix attempts,
- test results,
- final outcomes.

No dashboard-specific transformation should be required. If a display needs data, that data belongs in the transcript contract.

## Artifact Storage

Artifacts are referenced by `ArtifactRefV1`.

Allowed artifact types:

- `screenshot`,
- `dom_snapshot`,
- `console_log`,
- `network_log`,
- `patch`,
- `test_report`,
- `trace`,
- `video`,
- `text_log`.

For the first build, local file paths are acceptable. Later versions may use object storage.

## Execution Commands

Recommended local commands:

```bash
python -m app.main
python -m agents.personas.run --config fixtures/persona_basic.json
python -m orchestrator.run --mode live
python -m shared.contracts.validate fixtures/
pytest
```
