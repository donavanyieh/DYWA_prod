from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.ai.gpt5_client import OpenAIJsonClient
from shared.contracts.models import (
    BugReportV1,
    ConfirmedBehaviorV1,
    FixTaskRefV1,
    FixTaskV1,
    ModelConfigV1,
    PromotionPolicyV1,
    RepoTargetV1,
    SandboxV1,
    VerifierClassification,
    VerifierDecisionV1,
    VerifierInputV1,
    VerifierNextAction,
)
from shared.io import read_json, write_json
from shared.logging import log
from shared.time import utc_now


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug[:80] or f"bug_{uuid4().hex[:8]}"


def read_expected_sources(paths: list[Path]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in paths:
        if path.exists() and path.is_file():
            sources[str(path)] = path.read_text()
    return sources


def nullable_model_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in {"", "null", "none"}:
        return None
    return value


def decision_from_payload(report: BugReportV1, payload: dict[str, Any]) -> VerifierDecisionV1:
    classification = VerifierClassification(str(payload["classification"]))
    canonical_bug_id = nullable_model_value(payload.get("canonical_bug_id"))
    if classification == VerifierClassification.CONFIRMED and not canonical_bug_id:
        canonical_bug_id = slugify(report.title)

    required_next_action = VerifierNextAction(str(payload["required_next_action"]))
    return VerifierDecisionV1(
        decision_id=f"verdict_{uuid4().hex[:10]}",
        run_id=report.run_id,
        report_id=report.report_id,
        created_at=utc_now(),
        classification=classification,
        confidence=float(payload["confidence"]),
        canonical_bug_id=canonical_bug_id,
        duplicate_of=nullable_model_value(payload.get("duplicate_of")),
        severity=nullable_model_value(payload.get("severity")),
        reasoning_summary=str(payload["reasoning_summary"]),
        required_next_action=required_next_action,
        fix_task=None,
        metadata={},
    )


def classify_report(
    *,
    report: BugReportV1,
    expected_sources: dict[str, str],
    related_reports: list[BugReportV1],
    model: ModelConfigV1,
) -> VerifierDecisionV1:
    log(f"Verifier: classifying report {report.report_id} with model {model.model_name}.")
    client = OpenAIJsonClient(
        model=model.model_name,
        reasoning_effort=model.reasoning_effort,
    )
    instructions = (
        "You are the verifier for an adaptive healing engine. Classify suspected "
        "shopping-app bug reports using evidence, expected behavior, and related reports. "
        "Do not assume planted bugs. Return JSON only."
    )
    prompt = json.dumps(
        {
            "report": report.model_dump(mode="json"),
            "related_reports": [item.model_dump(mode="json") for item in related_reports],
            "expected_behavior_sources": expected_sources,
            "allowed_response_shape": {
                "classification": "confirmed | duplicate | invalid | needs_more_evidence",
                "confidence": "0 to 1",
                "canonical_bug_id": "stable id when confirmed or duplicate",
                "duplicate_of": "canonical id when duplicate, else null",
                "severity": "low | medium | high | critical | null",
                "reasoning_summary": "short explanation",
                "required_next_action": "send_to_fixing_agent | ignore | request_more_evidence | link_to_existing_bug"
            },
        },
        indent=2,
    )
    decision = client.create_json(instructions=instructions, prompt=prompt)
    log(
        f"Verifier: model returned {decision.get('classification')} "
        f"for report {report.report_id}."
    )
    return decision_from_payload(report, decision)


def classify_reports_batch(
    *,
    reports: list[BugReportV1],
    expected_sources: dict[str, str],
    model: ModelConfigV1,
) -> dict[str, VerifierDecisionV1]:
    if not reports:
        return {}

    log(f"Verifier: batch classifying {len(reports)} report(s) with model {model.model_name}.")
    client = OpenAIJsonClient(
        model=model.model_name,
        reasoning_effort=model.reasoning_effort,
    )
    instructions = (
        "You are the verifier for an adaptive healing engine. Classify suspected "
        "shopping-app bug reports using evidence, expected behavior, and all reports "
        "from the current run. Deduplicate reports that describe the same underlying "
        "bug. Do not assume planted bugs. Return JSON only."
    )
    prompt = json.dumps(
        {
            "reports": [report.model_dump(mode="json") for report in reports],
            "expected_behavior_sources": expected_sources,
            "deduplication_rules": [
                "Return exactly one decision for every input report_id.",
                "When multiple reports describe the same underlying bug, choose the clearest report as canonical.",
                "Mark the canonical report as confirmed when the evidence is sufficient.",
                "Mark same-bug non-canonical reports as duplicate and set duplicate_of to the canonical report_id.",
                "Use needs_more_evidence when evidence is insufficient, even if reports are similar.",
            ],
            "allowed_response_shape": {
                "decisions": [
                    {
                        "report_id": "must match one input report_id",
                        "classification": "confirmed | duplicate | invalid | needs_more_evidence",
                        "confidence": "0 to 1",
                        "canonical_bug_id": "stable id when confirmed or duplicate",
                        "duplicate_of": "canonical report_id when duplicate, else null",
                        "severity": "low | medium | high | critical | null",
                        "reasoning_summary": "short explanation",
                        "required_next_action": "send_to_fixing_agent | ignore | request_more_evidence | link_to_existing_bug",
                    }
                ]
            },
        },
        indent=2,
    )
    response = client.create_json(instructions=instructions, prompt=prompt)
    raw_decisions = response.get("decisions")
    if not isinstance(raw_decisions, list):
        raise ValueError("Batch verifier response must contain a decisions list.")

    reports_by_id = {report.report_id: report for report in reports}
    decisions: dict[str, VerifierDecisionV1] = {}
    for raw_decision in raw_decisions:
        if not isinstance(raw_decision, dict):
            raise ValueError("Each batch verifier decision must be an object.")
        report_id = str(raw_decision.get("report_id", ""))
        if report_id not in reports_by_id:
            raise ValueError(f"Batch verifier returned unknown report_id: {report_id}")
        if report_id in decisions:
            raise ValueError(f"Batch verifier returned duplicate decision for: {report_id}")
        decisions[report_id] = decision_from_payload(reports_by_id[report_id], raw_decision)

    missing = set(reports_by_id) - set(decisions)
    if missing:
        raise ValueError(f"Batch verifier omitted decision(s) for: {', '.join(sorted(missing))}")

    log(f"Verifier: batch model returned {len(decisions)} decision(s).")
    return decisions


def write_verifier_outputs(
    *,
    report: BugReportV1,
    decision: VerifierDecisionV1,
    output_dir: Path,
    expected_source_paths: list[Path],
    repo: RepoTargetV1,
    sandbox_root: str,
    promotion_policy: PromotionPolicyV1,
    related_reports: list[BugReportV1],
) -> dict[str, str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    fix_task_path = None
    if decision.classification == VerifierClassification.CONFIRMED:
        log(f"Verifier: report {report.report_id} confirmed; building fix task.")
        fix_task = build_fix_task(
            report,
            decision,
            repo=repo,
            sandbox_root=sandbox_root,
            promotion_policy=promotion_policy,
        )
        decision.fix_task = FixTaskRefV1(task_id=fix_task.task_id)
        fix_task_path = output_dir / "fix_task.json"
        write_json(fix_task_path, fix_task)
        log(f"Verifier: fix task written to {fix_task_path}.")
    else:
        log(f"Verifier: report {report.report_id} does not require a fix task.")

    decision_path = output_dir / "verifier_decision.json"
    write_json(decision_path, decision)
    log(f"Verifier: decision written to {decision_path}.")
    verifier_input = VerifierInputV1(
        run_id=report.run_id,
        report=report,
        related_reports=related_reports,
        known_confirmed_bugs=[],
        expected_behavior_sources=[str(path) for path in expected_source_paths],
        transcript_events=report.evidence.transcript_event_ids,
        artifacts=report.evidence.artifacts,
    )
    write_json(output_dir / "verifier_input.json", verifier_input)
    return {
        "decision_path": str(decision_path),
        "fix_task_path": str(fix_task_path) if fix_task_path else None,
    }


def build_fix_task(
    report: BugReportV1,
    decision: VerifierDecisionV1,
    *,
    repo: RepoTargetV1,
    sandbox_root: str,
    promotion_policy: PromotionPolicyV1,
) -> FixTaskV1:
    task_id = f"fix_{uuid4().hex[:10]}"
    return FixTaskV1(
        task_id=task_id,
        run_id=report.run_id,
        canonical_bug_id=decision.canonical_bug_id or slugify(report.title),
        created_at=utc_now(),
        source_report_ids=[report.report_id],
        title=report.title,
        confirmed_behavior=ConfirmedBehaviorV1(
            observed=report.observed_behavior,
            expected=report.expected_behavior,
        ),
        reproduction_steps=report.reproduction_steps,
        evidence_artifacts=[artifact.artifact_id for artifact in report.evidence.artifacts],
        repo=repo,
        sandbox=SandboxV1(mode="copy", path=f"{sandbox_root}/{report.run_id}/{task_id}"),
        promotion_policy=promotion_policy,
        metadata={},
    )


def verify_to_files(
    *,
    bug_report_path: Path,
    output_dir: Path,
    expected_source_paths: list[Path],
    repo: RepoTargetV1,
    sandbox_root: str,
    promotion_policy: PromotionPolicyV1,
    model: ModelConfigV1,
    related_reports: list[BugReportV1] | None = None,
) -> dict[str, str | None]:
    report = BugReportV1.model_validate(read_json(bug_report_path))
    log(f"Verifier: loaded bug report {report.report_id} from {bug_report_path}.")
    related_reports = related_reports or []
    expected_sources = read_expected_sources(expected_source_paths)
    log(
        f"Verifier: using {len(expected_sources)} expected behavior source(s) "
        f"and {len(related_reports)} related report(s)."
    )
    decision = classify_report(
        report=report,
        expected_sources=expected_sources,
        related_reports=related_reports,
        model=model,
    )

    return write_verifier_outputs(
        report=report,
        decision=decision,
        output_dir=output_dir,
        expected_source_paths=expected_source_paths,
        repo=repo,
        sandbox_root=sandbox_root,
        promotion_policy=promotion_policy,
        related_reports=related_reports,
    )


def verify_batch_to_files(
    *,
    bug_report_paths: list[Path],
    output_root: Path,
    expected_source_paths: list[Path],
    repo: RepoTargetV1,
    sandbox_root: str,
    promotion_policy: PromotionPolicyV1,
    model: ModelConfigV1,
) -> list[dict[str, str | None]]:
    reports = [BugReportV1.model_validate(read_json(path)) for path in bug_report_paths]
    log(f"Verifier: loaded {len(reports)} bug report(s) for batch triage.")
    expected_sources = read_expected_sources(expected_source_paths)
    log(
        f"Verifier: using {len(expected_sources)} expected behavior source(s) "
        f"for batch triage."
    )
    decisions = classify_reports_batch(
        reports=reports,
        expected_sources=expected_sources,
        model=model,
    )

    results: list[dict[str, str | None]] = []
    for index, report in enumerate(reports, start=1):
        related_reports = [item for item in reports if item.report_id != report.report_id]
        results.append(
            write_verifier_outputs(
                report=report,
                decision=decisions[report.report_id],
                output_dir=output_root / f"report_{index:03d}",
                expected_source_paths=expected_source_paths,
                repo=repo,
                sandbox_root=sandbox_root,
                promotion_policy=promotion_policy,
                related_reports=related_reports,
            )
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live model-backed verifier.")
    parser.add_argument("--bug-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-source", type=Path, action="append", default=[])
    parser.add_argument("--repo-path", default=".")
    parser.add_argument("--entrypoint", required=True)
    parser.add_argument("--test-command", required=True)
    parser.add_argument("--sandbox-root", default=".sandbox")
    parser.add_argument("--promotion-target", required=True)
    parser.add_argument("--model", default="gpt-5")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high", "none"],
        default="medium",
    )
    args = parser.parse_args()
    reasoning_effort = None if args.reasoning_effort == "none" else args.reasoning_effort

    result = verify_to_files(
        bug_report_path=args.bug_report,
        output_dir=args.output_dir,
        expected_source_paths=args.expected_source,
        repo=RepoTargetV1(
            path=args.repo_path,
            entrypoint=args.entrypoint,
            test_command=args.test_command,
        ),
        sandbox_root=args.sandbox_root,
        promotion_policy=PromotionPolicyV1(
            target_file=args.promotion_target,
            requires_tests_green=True,
            requires_contract_validation=True,
        ),
        model=ModelConfigV1(model_name=args.model, reasoning_effort=reasoning_effort),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
