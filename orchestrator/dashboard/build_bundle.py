from __future__ import annotations

import json
from pathlib import Path

from shared.contracts.models import (
    BugReportV1,
    DashboardRunBundleV1,
    FixResultV1,
    RunStateV1,
    TranscriptEventV1,
    VerifierDecisionV1,
)
from shared.io import read_json, write_json


def read_jsonl_events(path: Path) -> list[TranscriptEventV1]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text().splitlines():
        if line.strip():
            events.append(TranscriptEventV1.model_validate(json.loads(line)))
    return events


def maybe_load(path: Path, model: type) -> object | None:
    if not path.exists():
        return None
    return model.model_validate(read_json(path))


def build_dashboard_bundle(run_dir: Path) -> DashboardRunBundleV1:
    run_state = RunStateV1.model_validate(read_json(run_dir / "run_state.json"))
    events: list[TranscriptEventV1] = []
    for transcript_path in sorted(run_dir.rglob("transcript.jsonl")):
        events.extend(read_jsonl_events(transcript_path))

    bug_reports = []
    for bug_report_path in sorted(run_dir.rglob("bug_report.json")):
        bug_report = maybe_load(bug_report_path, BugReportV1)
        if bug_report:
            bug_reports.append(bug_report)

    verifier_decisions = []
    for decision_path in sorted(run_dir.rglob("verifier_decision.json")):
        decision = maybe_load(decision_path, VerifierDecisionV1)
        if decision:
            verifier_decisions.append(decision)

    fix_results = []
    for fix_result_path in sorted(run_dir.rglob("fix_result.json")):
        fix_result = maybe_load(fix_result_path, FixResultV1)
        if fix_result:
            fix_results.append(fix_result)

    artifacts = []
    for event in events:
        artifacts.extend(event.artifacts)
    for report in bug_reports:
        artifacts.extend(report.evidence.artifacts)
    for result in fix_results:
        artifacts.extend(result.artifacts)

    return DashboardRunBundleV1(
        run_state=run_state,
        events=events,
        bug_reports=bug_reports,
        verifier_decisions=verifier_decisions,
        fix_results=fix_results,
        artifacts=artifacts,
    )


def write_dashboard_bundle(run_dir: Path) -> Path:
    bundle = build_dashboard_bundle(run_dir)
    output = run_dir / "dashboard_bundle.json"
    write_json(output, bundle)
    return output
