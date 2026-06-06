# Adaptive Healing Engine

This repository is the first live-runner slice of the adaptive healing engine.

It includes:

- shared versioned contracts,
- a minimal FastAPI shopping app with a planted cart-total bug,
- Stage 0 reset support for restoring the buggy `app/main.py`,
- live model-backed persona and verifier entrypoints,
- a fixing-agent sandbox entrypoint,
- an orchestrator that connects the components through contract JSON.

## Setup

Run these once from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Set your OpenAI key before running the live agents. There is no mock mode in the runtime path.

```bash
export OPENAI_API_KEY=...
```

## Run The Full Live Workflow

The orchestrator starts the shopping app, restores Stage 0, launches the configured live personas, verifies any reported inconsistencies, sends confirmed bugs to the fixing agent, runs the configured tests, and writes dashboard artifacts.

```bash
python -m orchestrator.run --mode live --config configs/run_config.json
```

When the run completes, the command prints an artifacts directory like:

```text
artifacts/run_ab12cd34
```

That directory contains the transcript JSON, screenshots, verifier decision, fix task, fix result, and `dashboard_bundle.json`.

Each persona action also writes a verbose decision artifact:

```text
artifacts/run_*/personas/<persona_id>/decision_000.json
```

Those files include the model name, page state, screenshot reference, recent history, selected action, reasoning, and consistency checks.

## View The Dashboard

Open [orchestrator/dashboard/index.html](/Users/donavanyieh/Documents/test/orchestrator/dashboard/index.html) in a browser, then choose the generated `dashboard_bundle.json` from the latest `artifacts/run_*` directory.

## Useful Checks

Validate all contract fixtures:

```bash
python -m shared.contracts.validate fixtures/contracts
python -m shared.contracts.validate configs/run_config.json
```

Run the generic app safety tests:

```bash
pytest
```

Restore the configured buggy Stage 0 state without running the full workflow:

```bash
python -m scripts.reset_stage0 --config configs/run_config.json
```

Run only the shopping app for manual inspection:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

Then visit `http://127.0.0.1:8765`.

## Configuration

The live run is controlled by [configs/run_config.json](/Users/donavanyieh/Documents/test/configs/run_config.json). Change this file when you change the demo app, port, persona goals, Stage 0 restore files, expected behavior sources, repo entrypoint, test command, or promotion target.

The default config currently runs five group-buy personas:

- `persona_gb_flow`
- `persona_gb_price`
- `persona_gb_contract`
- `persona_gb_security`
- `persona_gb_data_integrity`

Add, remove, or edit personas under `personas`.

Each persona has an action budget:

```json
"constraints": {
  "max_duration_ms": 120000,
  "max_actions": 30,
  "viewport": {
    "width": 1440,
    "height": 900
  },
  "headless": false,
  "slow_mo_ms": 250
}
```

`max_actions` is a ceiling, not a required count. On every step, the persona sends the current screenshot, page state, recent history, goal, and traits to the configured model. The model chooses one of:

- `click_button`
- `fill_input`
- `report_bug`
- `finish`

The persona can stop early by returning `finish` when the goal is reached, impossible, or no useful next action remains. It stops immediately with `report_bug` when it has enough evidence to flag an inconsistency.

Set `headless` to `false` to watch the browser. Increase `slow_mo_ms` if you want actions to be easier to follow.

## Model Selection

Models are configured in [configs/run_config.json](/Users/donavanyieh/Documents/test/configs/run_config.json). Each persona has its own model block, and the verifier and fixing agent have separate model blocks:

```json
{
  "model": {
    "provider": "openai",
    "model_name": "gpt-5",
    "mode": "live",
    "reasoning_effort": "medium"
  }
}
```

Change `model_name` to use a different OpenAI model. If the model does not support the `reasoning` parameter, set `reasoning_effort` to `null`.

The current config uses port `8765`. If that port is busy, change these values together:

- `app.start_command`
- `app.base_url`
- `app.health_url`

## Current Demo Behavior

The Stage 0 seed includes a placeholder group-buy flow to be replaced by the real feature. The configured group-buy personas target its five-step journey: click `Group Buy`, reach checkout, click `Place Order`, reach confirmation, then return to the `Group Buy` page.

The runtime does not pass a bug oracle to the agents. Live personas are expected to flag inconsistencies from observed UI state, and the verifier reviews the persona's evidence. Tests are a configurable safety gate; the fixing agent may add regression coverage dynamically when it patches a confirmed report.
