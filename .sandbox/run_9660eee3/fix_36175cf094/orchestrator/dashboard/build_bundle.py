from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from shared.time import utc_now


def read_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text())
    return data if isinstance(data, dict) else {}


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(payload, "model_dump"):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def read_jsonl_events(path: Path) -> list[Any]:
    from shared.contracts.models import TranscriptEventV1

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
    return model.model_validate(read_json_file(path))


def maybe_read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = read_json_file(path)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def file_timestamp(path: Path) -> str | None:
    if not path.exists():
        return None
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return modified.strftime("%Y-%m-%dT%H:%M:%SZ")


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def run_metadata(run_dir: Path, artifacts_dir: Path) -> dict[str, Any] | None:
    run_state = maybe_read_json(run_dir / "run_state.json")
    if not run_state:
        return None

    persona_configs = []
    for config_path in sorted(run_dir.glob("personas/*/persona_config.json")):
        config = maybe_read_json(config_path)
        if config:
            persona_configs.append(config)

    bug_report_count = len(list(run_dir.rglob("bug_report.json")))
    verifier_decision_count = len(list(run_dir.rglob("verifier_decision.json")))
    fix_result_count = len(list(run_dir.rglob("fix_result.json")))
    transcript_event_count = sum(count_jsonl(path) for path in run_dir.rglob("transcript.jsonl"))
    screenshot_count = len(list(run_dir.rglob("screen_*.png")))
    decision_artifact_count = len(list(run_dir.rglob("decision_*.json")))
    bundle_path = run_dir / "dashboard_bundle.json"
    relative_run_dir = run_dir.relative_to(artifacts_dir).as_posix()

    model_names = sorted(
        {
            config.get("model", {}).get("model_name")
            for config in persona_configs
            if isinstance(config.get("model"), dict)
            and config.get("model", {}).get("model_name")
        }
    )

    return {
        "run_id": run_state["run_id"],
        "run_dir": relative_run_dir,
        "bundle_path": bundle_path.relative_to(artifacts_dir).as_posix()
        if bundle_path.exists()
        else None,
        "status": run_state["status"],
        "stage": run_state["stage"],
        "started_at": run_state["started_at"],
        "completed_at": run_state.get("completed_at"),
        "updated_at": file_timestamp(run_dir / "run_state.json"),
        "components": run_state.get("components", {}),
        "summary": run_state.get("summary", {}),
        "personas": [config.get("persona_id") for config in persona_configs if config.get("persona_id")],
        "models": model_names,
        "counts": {
            "bug_reports": bug_report_count,
            "verifier_decisions": verifier_decision_count,
            "fix_results": fix_result_count,
            "transcript_events": transcript_event_count,
            "screenshots": screenshot_count,
            "decision_artifacts": decision_artifact_count,
        },
        "has_bundle": bundle_path.exists(),
    }


def build_dashboard_bundle(run_dir: Path) -> Any:
    from shared.contracts.models import (
        BugReportV1,
        DashboardRunBundleV1,
        FixResultV1,
        RunStateV1,
        TranscriptEventV1,
        VerifierDecisionV1,
    )

    run_state = RunStateV1.model_validate(read_json_file(run_dir / "run_state.json"))
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
    write_json_file(output, bundle)
    write_dashboard_index(run_dir.parent)
    return output


def build_dashboard_index(artifacts_dir: Path) -> dict[str, Any]:
    runs = []
    for run_dir in sorted(artifacts_dir.glob("run_*")):
        if run_dir.is_dir():
            metadata = run_metadata(run_dir, artifacts_dir)
            if metadata:
                runs.append(metadata)

    runs.sort(key=lambda item: item.get("started_at", ""), reverse=True)
    totals = {
        "runs": len(runs),
        "running": sum(1 for run in runs if run.get("status") == "running"),
        "completed": sum(1 for run in runs if run.get("status") == "completed"),
        "failed": sum(1 for run in runs if run.get("status") == "failed"),
        "reports": sum(run.get("summary", {}).get("reports_total", 0) for run in runs),
        "confirmed": sum(run.get("summary", {}).get("confirmed_total", 0) for run in runs),
        "fixed": sum(run.get("summary", {}).get("fixed_total", 0) for run in runs),
    }
    return {
        "schema_version": "1.0.0",
        "generated_at": utc_now(),
        "artifacts_dir": artifacts_dir.as_posix(),
        "totals": totals,
        "runs": runs,
    }


def write_dashboard_index(artifacts_dir: Path) -> Path:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    index = build_dashboard_index(artifacts_dir)
    output = artifacts_dir / "dashboard_index.json"
    write_json_file(output, index)
    return output


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Build dashboard bundles and run index.")
    parser.add_argument("--run-dir", type=Path, help="Run directory to bundle.")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("artifacts"),
        help="Artifacts directory to index.",
    )
    parser.add_argument(
        "--index-only",
        action="store_true",
        help="Only rebuild dashboard_index.json.",
    )
    args = parser.parse_args()

    if args.run_dir and not args.index_only:
        output = write_dashboard_bundle(args.run_dir)
        print(f"Dashboard bundle: {output}")

    index_output = write_dashboard_index(args.artifacts_dir)
    print(f"Dashboard index: {index_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
