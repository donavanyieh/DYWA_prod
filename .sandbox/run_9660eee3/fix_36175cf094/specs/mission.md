# Adaptive Healing Engine Mission

## Product Vision

Build a demo-ready adaptive healing engine that discovers, verifies, fixes, tests, and promotes bug fixes in a sandboxed shopping application without hardcoded bug knowledge.

The system demonstrates a closed loop:

1. AI-driven persona agents explore a buggy shopping site.
2. A verifier triages reported issues using evidence and expected behavior.
3. A Codex-powered fixing agent patches confirmed bugs in a sandbox.
4. Tests and verification gates decide whether fixes can be promoted.
5. A dashboard shows the full workstream from discovery to fix.

## Demo Goal

The demo should make the autonomous workflow visible and credible. An observer should be able to see:

- personas interacting with the app,
- screenshots and actions that led to a suspected bug,
- verifier reasoning and deduplication,
- confirmed bugs sent to the fixing agent,
- patch attempts and test results,
- final fix status,
- reset behavior that returns the app to the original buggy state.

## Non-Negotiable Principles

- No component may hardcode planted bug identities, selectors, fixes, or triage outcomes.
- All component boundaries use shared versioned data contracts.
- Every component validates inbound and outbound payloads.
- Every agent emits transcripts suitable for dashboard display without custom transformation.
- The first build prioritizes contract completeness and integration reliability over feature richness.
- Owners must be able to develop against contract fixtures and live runner interfaces before full integration.

## Workstreams And Owners

| Owner | Workstream | Primary Responsibility |
| --- | --- | --- |
| Owner 1 | Shopping App | FastAPI app, frontend, planted bugs, reset state, app tests |
| Owner 2 | Persona Agents | Playwright exploration, screenshot capture, AI observation, bug reports, persona transcripts |
| Owner 3 | Fixing Agent | Sandbox patch loop, tests, fix validation, patch transcripts, promotion gate |
| Owner 4 | Orchestrator, Verifier, Dashboard | Workflow coordination, AI triage, dedupe, contract validation, transcript store, dashboard |

## Success Criteria

The first integrated version is successful when:

- Stage 0 can reset the app to the original buggy state.
- At least one persona agent can explore the app autonomously.
- Persona output validates against `BugReportV1` and `TranscriptEventV1`.
- The verifier classifies reports as confirmed, duplicate, invalid, or needs more evidence.
- At least one confirmed bug reaches the fixing agent through `FixTaskV1`.
- The fixing agent patches in a sandbox and runs tests before promotion.
- The dashboard renders the full transcript stream from JSON contracts.
- Contract tests pass for all component inputs and outputs.

## Non-Goals For The First Build

- Production-grade ecommerce behavior.
- Large persona populations.
- Perfect AI accuracy.
- Automatic deployment beyond the local demo environment.
- Complex multi-branch git workflows.
- Rich analytics beyond the transcript-driven dashboard.

## Operating Constraints

- Local-first execution.
- Sandbox-first patching.
- Deterministic reset command.
- Configurable OpenAI model interface for all AI-driven agents, with GPT-5 as the default.
- No private field names or undocumented enum values.
- All timestamps use ISO 8601 UTC.
- All durations use milliseconds.
- All IDs are strings and globally unique within a run.
