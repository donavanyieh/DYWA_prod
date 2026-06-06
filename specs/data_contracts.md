# Data Contracts

## Contract Rules

- Contract version: `1.0.0`
- Serialization format: JSON
- Timestamps: ISO 8601 UTC, for example `2026-06-06T12:00:00Z`
- Durations: integer milliseconds
- IDs: strings
- Enum values: lowercase snake case
- Unknown fields: rejected unless `metadata` is explicitly provided
- Artifacts: referenced, not embedded
- Every payload includes `schema_version`

## Shared Types

### ArtifactRefV1

```json
{
  "schema_version": "1.0.0",
  "artifact_id": "art_001",
  "type": "screenshot",
  "uri": "artifacts/run_001/persona_001/screen_001.png",
  "mime_type": "image/png",
  "created_at": "2026-06-06T12:00:00Z",
  "sha256": "optional_hash",
  "metadata": {
    "viewport": "1440x900"
  }
}
```

Allowed `type` values:

- `screenshot`
- `dom_snapshot`
- `console_log`
- `network_log`
- `patch`
- `test_report`
- `trace`
- `video`
- `text_log`

### ErrorV1

```json
{
  "schema_version": "1.0.0",
  "code": "playwright_timeout",
  "message": "Timed out waiting for checkout button",
  "recoverable": true,
  "details": {
    "timeout_ms": 5000
  }
}
```

### TranscriptEventV1

```json
{
  "schema_version": "1.0.0",
  "event_id": "evt_001",
  "run_id": "run_001",
  "source": "persona_agent",
  "source_id": "persona_budget_buyer",
  "event_type": "action_taken",
  "status": "completed",
  "timestamp": "2026-06-06T12:00:01Z",
  "duration_ms": 840,
  "summary": "Clicked Add to cart on product detail page.",
  "artifacts": [],
  "payload": {
    "action": "click",
    "target": "Add to cart button"
  },
  "error": null
}
```

Allowed `source` values:

- `shopping_app`
- `persona_agent`
- `verifier`
- `fixing_agent`
- `orchestrator`
- `dashboard`

Allowed `status` values:

- `started`
- `completed`
- `failed`
- `skipped`

## Persona Agent Contracts

### PersonaConfigV1

Input to persona agent.

```json
{
  "schema_version": "1.0.0",
  "run_id": "run_001",
  "persona_id": "persona_budget_buyer",
  "app_base_url": "http://localhost:8000",
  "goal": "Find an affordable phone case and complete checkout.",
  "traits": {
    "patience": "medium",
    "risk_tolerance": "low",
    "shopping_style": "price_sensitive"
  },
  "constraints": {
    "max_duration_ms": 120000,
    "max_actions": 40,
    "viewport": {
      "width": 1440,
      "height": 900
    }
  },
  "artifact_dir": "artifacts/run_001/persona_budget_buyer",
  "model": {
    "provider": "openai",
    "model_name": "gpt-5",
    "mode": "live"
  }
}
```

All AI-driven runtime components must use live model calls. Contract fixtures may include sample outputs for validation, but no component should implement a mock decision path for normal development or integration. Model names are configurable through `ModelConfigV1`; GPT-5 remains the default. If a selected model does not support the `reasoning` parameter, set `reasoning_effort` to `null`.

### BugReportV1

Output from persona agent to verifier.

```json
{
  "schema_version": "1.0.0",
  "report_id": "bugrep_001",
  "run_id": "run_001",
  "persona_id": "persona_budget_buyer",
  "created_at": "2026-06-06T12:02:00Z",
  "title": "Cart total did not update after quantity changed",
  "severity_guess": "medium",
  "confidence": 0.78,
  "observed_behavior": "The item quantity changed from 1 to 2, but the displayed total stayed the same.",
  "expected_behavior": "The cart total should update when quantity changes.",
  "reproduction_steps": [
    "Open product detail page.",
    "Add product to cart.",
    "Open cart.",
    "Increase quantity from 1 to 2.",
    "Observe total price."
  ],
  "evidence": {
    "transcript_event_ids": ["evt_001", "evt_002", "evt_003"],
    "artifacts": [
      {
        "schema_version": "1.0.0",
        "artifact_id": "art_screen_003",
        "type": "screenshot",
        "uri": "artifacts/run_001/persona_budget_buyer/cart_total.png",
        "mime_type": "image/png",
        "created_at": "2026-06-06T12:01:58Z",
        "sha256": null,
        "metadata": {}
      }
    ]
  },
  "environment": {
    "app_base_url": "http://localhost:8000",
    "browser": "chromium",
    "viewport": "1440x900"
  },
  "metadata": {}
}
```

Allowed `severity_guess` values:

- `low`
- `medium`
- `high`
- `critical`

## Verifier Contracts

### VerifierInputV1

```json
{
  "schema_version": "1.0.0",
  "run_id": "run_001",
  "report": {
    "schema_version": "1.0.0",
    "report_id": "bugrep_001"
  },
  "related_reports": [],
  "known_confirmed_bugs": [],
  "expected_behavior_sources": [
    "specs/app_expected_behavior.md",
    "app/tests/test_cart.py"
  ],
  "transcript_events": ["evt_001", "evt_002", "evt_003"],
  "artifacts": ["art_screen_003"]
}
```

Implementations may pass the full nested `BugReportV1` and full event/artifact objects. If references are used, the orchestrator must provide a resolver.

### VerifierDecisionV1

```json
{
  "schema_version": "1.0.0",
  "decision_id": "verdict_001",
  "run_id": "run_001",
  "report_id": "bugrep_001",
  "created_at": "2026-06-06T12:03:00Z",
  "classification": "confirmed",
  "confidence": 0.86,
  "canonical_bug_id": "bug_cart_total_quantity",
  "duplicate_of": null,
  "severity": "medium",
  "reasoning_summary": "The report includes clear steps and a screenshot showing quantity changed while the total did not update.",
  "required_next_action": "send_to_fixing_agent",
  "fix_task": {
    "schema_version": "1.0.0",
    "task_id": "fix_001"
  },
  "metadata": {}
}
```

Allowed `classification` values:

- `confirmed`
- `duplicate`
- `invalid`
- `needs_more_evidence`

Allowed `required_next_action` values:

- `send_to_fixing_agent`
- `ignore`
- `request_more_evidence`
- `link_to_existing_bug`

## Fixing Agent Contracts

### FixTaskV1

Input to fixing agent.

```json
{
  "schema_version": "1.0.0",
  "task_id": "fix_001",
  "run_id": "run_001",
  "canonical_bug_id": "bug_cart_total_quantity",
  "created_at": "2026-06-06T12:03:10Z",
  "source_report_ids": ["bugrep_001"],
  "title": "Cart total did not update after quantity changed",
  "confirmed_behavior": {
    "observed": "Cart quantity changed but total stayed unchanged.",
    "expected": "Cart total updates after quantity changes."
  },
  "reproduction_steps": [
    "Add product to cart.",
    "Open cart.",
    "Increase quantity.",
    "Observe total."
  ],
  "evidence_artifacts": ["art_screen_003"],
  "repo": {
    "path": ".",
    "entrypoint": "app/main.py",
    "test_command": "pytest"
  },
  "sandbox": {
    "mode": "copy",
    "path": ".sandbox/run_001/fix_001"
  },
  "promotion_policy": {
    "target_file": "app/main.py",
    "requires_tests_green": true,
    "requires_contract_validation": true
  },
  "metadata": {}
}
```

### FixResultV1

Output from fixing agent.

```json
{
  "schema_version": "1.0.0",
  "result_id": "fixres_001",
  "task_id": "fix_001",
  "run_id": "run_001",
  "canonical_bug_id": "bug_cart_total_quantity",
  "status": "fixed",
  "started_at": "2026-06-06T12:04:00Z",
  "completed_at": "2026-06-06T12:08:30Z",
  "duration_ms": 270000,
  "summary": "Updated cart total recalculation and added a regression test.",
  "changed_files": [
    "app/main.py",
    "app/tests/test_cart.py"
  ],
  "artifacts": [
    {
      "schema_version": "1.0.0",
      "artifact_id": "art_patch_001",
      "type": "patch",
      "uri": "artifacts/run_001/fix_001/patch.diff",
      "mime_type": "text/x-diff",
      "created_at": "2026-06-06T12:08:00Z",
      "sha256": null,
      "metadata": {}
    }
  ],
  "tests": {
    "command": "pytest",
    "status": "passed",
    "passed": 12,
    "failed": 0,
    "duration_ms": 3400,
    "report_artifact_id": "art_test_001"
  },
  "promoted": true,
  "error": null,
  "metadata": {}
}
```

Allowed `status` values:

- `fixed`
- `not_reproduced`
- `failed`
- `needs_human_review`

Allowed test `status` values:

- `passed`
- `failed`
- `not_run`

## Orchestrator Contracts

### RunStateV1

```json
{
  "schema_version": "1.0.0",
  "run_id": "run_001",
  "status": "running",
  "started_at": "2026-06-06T12:00:00Z",
  "completed_at": null,
  "stage": "persona_exploration",
  "components": {
    "shopping_app": "running",
    "persona_agents": "running",
    "verifier": "idle",
    "fixing_agent": "idle",
    "dashboard": "running"
  },
  "summary": {
    "reports_total": 0,
    "confirmed_total": 0,
    "fixed_total": 0,
    "invalid_total": 0,
    "duplicate_total": 0
  }
}
```

Allowed run `status` values:

- `created`
- `running`
- `completed`
- `failed`
- `cancelled`

Allowed `stage` values:

- `stage_0_reset`
- `persona_exploration`
- `verification`
- `fixing`
- `integration_test`
- `complete`

### Stage0ResetResultV1

```json
{
  "schema_version": "1.0.0",
  "run_id": "run_001",
  "reset_id": "reset_001",
  "status": "completed",
  "started_at": "2026-06-06T11:59:50Z",
  "completed_at": "2026-06-06T12:00:00Z",
  "restored_files": ["app/main.py"],
  "bug_seed": "demo_seed_001",
  "error": null
}
```

## Dashboard Contract

### DashboardRunBundleV1

The dashboard reads this directly.

```json
{
  "schema_version": "1.0.0",
  "run_state": {
    "schema_version": "1.0.0",
    "run_id": "run_001"
  },
  "events": [],
  "bug_reports": [],
  "verifier_decisions": [],
  "fix_results": [],
  "artifacts": []
}
```

For JSONL storage, each line should be one `TranscriptEventV1`. Summary objects may be materialized into `DashboardRunBundleV1` by the orchestrator.
