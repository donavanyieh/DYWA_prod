from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import Page, sync_playwright

from shared.ai.gpt5_client import OpenAIJsonClient
from shared.contracts.models import (
    ArtifactRefV1,
    BugEnvironmentV1,
    BugEvidenceV1,
    BugReportV1,
    EventSource,
    EventStatus,
    PersonaConfigV1,
    TranscriptEventV1,
)
from shared.io import append_jsonl, read_json, write_json
from shared.logging import log
from shared.time import utc_now


def describe_page(page: Page) -> dict[str, object]:
    buttons = [button.inner_text().strip() for button in page.locator("button").all()]
    links = [link.inner_text().strip() for link in page.locator("a").all()]
    inputs = []
    for index, input_element in enumerate(page.locator("input").all()):
        inputs.append(
            {
                "index": index,
                "type": input_element.get_attribute("type") or "text",
                "value": input_element.input_value(),
            }
        )
    return {
        "url": page.url,
        "text": page.locator("body").inner_text(timeout=2000),
        "buttons": buttons,
        "links": links,
        "inputs": inputs,
    }


def record_event(
    *,
    transcript_path: Path,
    run_id: str,
    persona_id: str,
    event_type: str,
    status: EventStatus,
    summary: str,
    duration_ms: int,
    artifacts: list[ArtifactRefV1] | None = None,
    payload: dict[str, object] | None = None,
) -> TranscriptEventV1:
    event = TranscriptEventV1(
        event_id=f"evt_{uuid4().hex[:10]}",
        run_id=run_id,
        source=EventSource.PERSONA_AGENT,
        source_id=persona_id,
        event_type=event_type,
        status=status,
        timestamp=utc_now(),
        duration_ms=duration_ms,
        summary=summary,
        artifacts=artifacts or [],
        payload=payload or {},
        error=None,
    )
    append_jsonl(transcript_path, event)
    return event


def screenshot_artifact(page: Page, artifact_dir: Path, index: int) -> ArtifactRefV1:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"screen_{index:03d}.png"
    page.screenshot(path=path, full_page=True)
    return ArtifactRefV1(
        artifact_id=f"art_{uuid4().hex[:10]}",
        type="screenshot",
        uri=str(path),
        mime_type="image/png",
        created_at=utc_now(),
        sha256=None,
        metadata={"viewport": "configured"},
    )


def decision_artifact(
    *,
    artifact_dir: Path,
    index: int,
    config: PersonaConfigV1,
    page_state: dict[str, object],
    screenshot: ArtifactRefV1,
    history: list[str],
    decision: dict[str, object],
) -> ArtifactRefV1:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / f"decision_{index:03d}.json"
    write_json(
        path,
        {
            "schema_version": "1.0.0",
            "created_at": utc_now(),
            "persona": {
                "id": config.persona_id,
                "goal": config.goal,
                "traits": config.traits,
            },
            "model": config.model.model_dump(mode="json"),
            "page_state": page_state,
            "screenshot_artifact": screenshot.model_dump(mode="json"),
            "recent_history": history[-8:],
            "decision": decision,
            "reasoning": decision.get("reasoning") or decision.get("reason"),
            "consistency_checks": decision.get("consistency_checks", []),
        },
    )
    return ArtifactRefV1(
        artifact_id=f"art_{uuid4().hex[:10]}",
        type="text_log",
        uri=str(path),
        mime_type="application/json",
        created_at=utc_now(),
        sha256=None,
        metadata={
            "kind": "persona_decision",
            "model_name": config.model.model_name,
        },
    )


def ask_for_action(
    *,
    client: OpenAIJsonClient,
    config: PersonaConfigV1,
    page_state: dict[str, object],
    screenshot: ArtifactRefV1,
    history: list[str],
    validation_feedback: list[str] | None = None,
) -> dict[str, object]:
    instructions = (
        "You are an autonomous ecommerce user persona. Choose the next browser action "
        "from the available controls. Do not assume planted bugs. Your main job is to "
        "notice inconsistencies a real user could observe: contradictions between an "
        "action and the visible result, mismatched numbers, inconsistent item state, "
        "conflicting messages, broken navigation, or checkout outcomes that do not match "
        "the page state. Report a bug only from observed evidence. Return finish when "
        "your goal is reached, when no useful next action remains, or when the goal is "
        "impossible from the current state. Return JSON only."
    )
    prompt = json.dumps(
        {
            "persona": {
                "id": config.persona_id,
                "goal": config.goal,
                "traits": config.traits,
            },
            "page_state": page_state,
            "recent_history": history[-8:],
            "validation_feedback": validation_feedback or [],
            "allowed_response_shape": {
                "action": "click_button | fill_input | report_bug | finish",
                "observation_summary": "what you see now",
                "reason": "short reason for the selected action",
                "reasoning": "detailed reasoning, including why this action or bug report is justified",
                "consistency_checks": [
                    "specific UI or state consistency checks you performed before deciding"
                ],
                "confidence": "0 to 1 confidence in the selected action or report",
                "stop_reason": "required when action is finish: goal_reached | impossible | no_useful_action | action_budget_nearly_exhausted",
                "button_text": "required for click_button",
                "input_index": "required for fill_input",
                "value": "required for fill_input",
                "bug_report": {
                    "title": "required for report_bug",
                    "severity_guess": "low | medium | high | critical",
                    "confidence": "0 to 1",
                    "observed_behavior": "what happened",
                    "expected_behavior": "what should have happened",
                    "reproduction_steps": ["step strings"]
                }
            },
        },
        indent=2,
    )
    return client.create_json(
        instructions=instructions,
        prompt=prompt,
        image_paths=[Path(screenshot.uri)],
    )


def validate_action(action: dict[str, object], page_state: dict[str, object]) -> list[str]:
    errors = []
    action_name = str(action.get("action", ""))
    if action_name not in {"click_button", "fill_input", "report_bug", "finish"}:
        return [f"Unsupported action '{action_name}'. Use click_button, fill_input, report_bug, or finish."]

    if action_name == "click_button":
        button_text = str(action.get("button_text", "")).strip()
        if not button_text:
            errors.append("click_button requires button_text matching one visible button.")
        elif button_text not in [str(button) for button in page_state.get("buttons", [])]:
            errors.append(
                f"button_text '{button_text}' is not one of the visible buttons: {page_state.get('buttons', [])}."
            )

    if action_name == "fill_input":
        inputs = page_state.get("inputs", [])
        if "input_index" not in action:
            errors.append("fill_input requires input_index.")
        else:
            try:
                input_index = int(action["input_index"])
                if input_index < 0 or input_index >= len(inputs):
                    errors.append(f"input_index {input_index} is outside visible input range 0..{len(inputs) - 1}.")
            except (TypeError, ValueError):
                errors.append("input_index must be an integer.")
        if "value" not in action:
            errors.append("fill_input requires value.")

    if action_name == "report_bug":
        report = action.get("bug_report")
        if not isinstance(report, dict):
            errors.append("report_bug requires bug_report object.")
        else:
            for field in (
                "title",
                "severity_guess",
                "confidence",
                "observed_behavior",
                "expected_behavior",
                "reproduction_steps",
            ):
                if field not in report:
                    errors.append(f"bug_report requires {field}.")

    if action_name == "finish" and "stop_reason" not in action:
        errors.append("finish requires stop_reason.")

    return errors


def ask_for_valid_action(
    *,
    client: OpenAIJsonClient,
    config: PersonaConfigV1,
    page_state: dict[str, object],
    screenshot: ArtifactRefV1,
    history: list[str],
    max_attempts: int = 3,
) -> dict[str, object]:
    validation_feedback: list[str] = []
    for _attempt in range(max_attempts):
        try:
            action = ask_for_action(
                client=client,
                config=config,
                page_state=page_state,
                screenshot=screenshot,
                history=history,
                validation_feedback=validation_feedback,
            )
        except Exception as exc:
            validation_feedback = [
                "Previous response could not be parsed as valid JSON. "
                "Return exactly one complete JSON object matching the allowed response shape.",
                f"Parser error: {exc.__class__.__name__}: {exc}",
            ]
            log(
                f"Persona {config.persona_id}: model response failed parsing: "
                f"{exc.__class__.__name__}: {exc}"
            )
            continue
        errors = validate_action(action, page_state)
        if not errors:
            return action
        validation_feedback = errors
        log(
            f"Persona {config.persona_id}: model action failed validation: "
            + " ".join(errors)
        )

    return {
        "action": "finish",
        "observation_summary": "Model did not return a valid action after retries.",
        "reason": "Action validation failed repeatedly.",
        "reasoning": "The model response omitted required fields or referenced unavailable controls.",
        "consistency_checks": [],
        "confidence": 0,
        "stop_reason": "no_useful_action",
    }


def execute_action(page: Page, action: dict[str, object]) -> str:
    action_name = str(action.get("action"))
    if action_name == "click_button":
        button_text = str(action["button_text"])
        page.get_by_role("button", name=button_text).first.click(timeout=5000)
        return f"Clicked button '{button_text}'."
    if action_name == "fill_input":
        input_index = int(action["input_index"])
        value = str(action["value"])
        element = page.locator("input").nth(input_index)
        element.fill(value, timeout=5000)
        element.press("Tab", timeout=5000)
        return f"Filled input {input_index} with '{value}'."
    if action_name in {"report_bug", "finish"}:
        return f"Stopped with action '{action_name}'."
    raise ValueError(f"Unsupported model action: {action_name}")


def bug_report_from_action(
    *,
    config: PersonaConfigV1,
    action: dict[str, object],
    event_ids: list[str],
    artifacts: list[ArtifactRefV1],
) -> BugReportV1:
    report = action.get("bug_report")
    if not isinstance(report, dict):
        raise ValueError("report_bug action must include bug_report object")

    viewport = config.constraints.viewport
    return BugReportV1(
        report_id=f"bugrep_{uuid4().hex[:10]}",
        run_id=config.run_id,
        persona_id=config.persona_id,
        created_at=utc_now(),
        title=str(report["title"]),
        severity_guess=str(report["severity_guess"]),
        confidence=float(report["confidence"]),
        observed_behavior=str(report["observed_behavior"]),
        expected_behavior=str(report["expected_behavior"]),
        reproduction_steps=[str(step) for step in report["reproduction_steps"]],
        evidence=BugEvidenceV1(
            transcript_event_ids=event_ids,
            artifacts=artifacts,
        ),
        environment=BugEnvironmentV1(
            app_base_url=config.app_base_url,
            browser="chromium",
            viewport=f"{viewport.width}x{viewport.height}",
        ),
        metadata={},
    )


def run_persona(config: PersonaConfigV1) -> dict[str, object]:
    artifact_dir = Path(config.artifact_dir)
    transcript_path = artifact_dir / "transcript.jsonl"
    bug_report_path = artifact_dir / "bug_report.json"
    log(
        f"Persona {config.persona_id}: initializing browser and model "
        f"{config.model.model_name}."
    )
    client = OpenAIJsonClient(
        model=config.model.model_name,
        reasoning_effort=config.model.reasoning_effort,
    )
    history: list[str] = []
    event_ids: list[str] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=config.constraints.headless,
            slow_mo=config.constraints.slow_mo_ms,
        )
        log(
            f"Persona {config.persona_id}: browser launched "
            f"headless={config.constraints.headless}, "
            f"slow_mo_ms={config.constraints.slow_mo_ms}."
        )
        page = browser.new_page(
            viewport={
                "width": config.constraints.viewport.width,
                "height": config.constraints.viewport.height,
            }
        )
        page.goto(config.app_base_url, wait_until="networkidle")
        log(f"Persona {config.persona_id}: opened {config.app_base_url}.")

        for index in range(config.constraints.max_actions):
            started = time.monotonic()
            log(
                f"Persona {config.persona_id}: action "
                f"{index + 1}/{config.constraints.max_actions} capturing screenshot."
            )
            screenshot = screenshot_artifact(page, artifact_dir, index)
            page_state = describe_page(page)
            log(f"Persona {config.persona_id}: asking model for next action.")
            action = ask_for_valid_action(
                client=client,
                config=config,
                page_state=page_state,
                screenshot=screenshot,
                history=history,
            )
            log(
                f"Persona {config.persona_id}: model chose "
                f"{action.get('action')} - {action.get('reason', 'no reason provided')}"
            )
            decision = decision_artifact(
                artifact_dir=artifact_dir,
                index=index,
                config=config,
                page_state=page_state,
                screenshot=screenshot,
                history=history,
                decision=action,
            )
            summary = execute_action(page, action)
            if action.get("reason"):
                summary = f"{summary} Reason: {action['reason']}"
            page.wait_for_timeout(400)
            duration_ms = int((time.monotonic() - started) * 1000)
            event = record_event(
                transcript_path=transcript_path,
                run_id=config.run_id,
                persona_id=config.persona_id,
                event_type="persona_action",
                status=EventStatus.COMPLETED,
                summary=summary,
                duration_ms=duration_ms,
                artifacts=[screenshot, decision],
                payload={
                    "model_decision": action,
                    "reasoning": action.get("reasoning") or action.get("reason"),
                    "observation_summary": action.get("observation_summary"),
                    "consistency_checks": action.get("consistency_checks", []),
                    "confidence": action.get("confidence"),
                    "page_state": page_state,
                },
            )
            event_ids.append(event.event_id)
            history.append(summary)
            log(f"Persona {config.persona_id}: {summary}")

            if action.get("action") == "report_bug":
                bug_report = bug_report_from_action(
                    config=config,
                    action=action,
                    event_ids=event_ids,
                    artifacts=[screenshot, decision],
                )
                write_json(bug_report_path, bug_report)
                log(f"Persona {config.persona_id}: bug report written to {bug_report_path}.")
                browser.close()
                return {
                    "transcript_path": str(transcript_path),
                    "bug_report_path": str(bug_report_path),
                }
            if action.get("action") == "finish":
                log(
                    f"Persona {config.persona_id}: finished exploration "
                    f"({action.get('stop_reason', 'no stop reason provided')})."
                )
                break

        browser.close()

    log(f"Persona {config.persona_id}: no bug report emitted.")
    return {"transcript_path": str(transcript_path), "bug_report_path": None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live model-backed persona agent.")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    config = PersonaConfigV1.model_validate(read_json(args.config))
    result = run_persona(config)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
