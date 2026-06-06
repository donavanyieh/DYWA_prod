from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from agents.fixing.run import fix_to_file
from agents.personas.run import run_persona
from orchestrator.dashboard.build_bundle import write_dashboard_bundle
from orchestrator.verifier.run import verify_to_files
from scripts.reset_stage0 import reset_stage0
from shared.contracts.models import (
    ComponentStatus,
    BugReportV1,
    PersonaConfigV1,
    PersonaTemplateV1,
    RunConfigV1,
    RunStage,
    RunStateV1,
    RunStatus,
    RunSummaryV1,
    VerifierClassification,
    VerifierDecisionV1,
)
from shared.io import read_json, write_json
from shared.logging import log
from shared.time import utc_now


ROOT = Path(__file__).resolve().parents[1]


def wait_for_app(url: str, timeout_s: int = 20) -> None:
    log(f"Waiting for app health check: {url}")
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    log("App health check passed.")
                    return
        except OSError:
            time.sleep(0.3)
    raise RuntimeError(f"Timed out waiting for app at {url}")


def write_run_state(
    *,
    run_dir: Path,
    run_id: str,
    status: RunStatus,
    stage: RunStage,
    started_at: str,
    completed_at: str | None,
    summary: RunSummaryV1,
) -> RunStateV1:
    state = RunStateV1(
        run_id=run_id,
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        stage=stage,
        components={
            "shopping_app": ComponentStatus.RUNNING,
            "persona_agents": ComponentStatus.RUNNING
            if stage == RunStage.PERSONA_EXPLORATION
            else ComponentStatus.IDLE,
            "verifier": ComponentStatus.RUNNING
            if stage == RunStage.VERIFICATION
            else ComponentStatus.IDLE,
            "fixing_agent": ComponentStatus.RUNNING
            if stage == RunStage.FIXING
            else ComponentStatus.IDLE,
            "dashboard": ComponentStatus.RUNNING,
        },
        summary=summary,
    )
    write_json(run_dir / "run_state.json", state)
    return state


def resolve_paths(paths: list[str]) -> list[Path]:
    resolved = []
    for path in paths:
        candidate = Path(path)
        resolved.append(candidate if candidate.is_absolute() else ROOT / candidate)
    return resolved


def resolve_command(command: list[str]) -> list[str]:
    return [sys.executable if item == "{python}" else item for item in command]


def build_persona_config(
    *,
    run_id: str,
    app_base_url: str,
    run_dir: Path,
    template: PersonaTemplateV1,
) -> PersonaConfigV1:
    return PersonaConfigV1(
        run_id=run_id,
        persona_id=template.persona_id,
        app_base_url=app_base_url,
        goal=template.goal,
        traits=template.traits,
        constraints=template.constraints,
        artifact_dir=str(run_dir / "personas" / template.persona_id),
        model=template.model,
    )


def run_live(config: RunConfigV1) -> Path:
    run_id = f"{config.run_id_prefix}_{uuid4().hex[:8]}"
    started_at = utc_now()
    run_dir = ROOT / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    log(f"Starting live run {run_id}.")
    log(f"Artifacts will be written to {run_dir}.")
    summary = RunSummaryV1(
        reports_total=0,
        confirmed_total=0,
        fixed_total=0,
        invalid_total=0,
        duplicate_total=0,
    )

    write_run_state(
        run_dir=run_dir,
        run_id=run_id,
        status=RunStatus.RUNNING,
        stage=RunStage.STAGE_0_RESET,
        started_at=started_at,
        completed_at=None,
        summary=summary,
    )
    log("Stage 0 reset starting.")
    reset_stage0(run_id, config, run_dir / "stage0_reset_result.json")
    log("Stage 0 reset completed.")

    app_cwd = Path(config.app.cwd)
    log(f"Starting app: {' '.join(resolve_command(config.app.start_command))}")
    app_process = subprocess.Popen(
        resolve_command(config.app.start_command),
        cwd=app_cwd if app_cwd.is_absolute() else ROOT / app_cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        wait_for_app(config.app.health_url or config.app.base_url)
        write_run_state(
            run_dir=run_dir,
            run_id=run_id,
            status=RunStatus.RUNNING,
            stage=RunStage.PERSONA_EXPLORATION,
            started_at=started_at,
            completed_at=None,
            summary=summary,
        )
        bug_report_paths: list[Path] = []
        log(f"Launching {len(config.personas)} persona(s).")
        for template in config.personas:
            log(f"Persona {template.persona_id} starting with model {template.model.model_name}.")
            persona_config = build_persona_config(
                run_id=run_id,
                app_base_url=config.app.base_url,
                run_dir=run_dir,
                template=template,
            )
            write_json(
                run_dir / "personas" / template.persona_id / "persona_config.json",
                persona_config,
            )
            persona_result = run_persona(persona_config)
            bug_report_path = persona_result.get("bug_report_path")
            if bug_report_path:
                bug_report_paths.append(Path(str(bug_report_path)))
                log(f"Persona {template.persona_id} reported a suspected bug: {bug_report_path}")
            else:
                log(f"Persona {template.persona_id} completed without a bug report.")

        if not bug_report_paths:
            log("No bug reports produced. Building dashboard bundle.")
            write_dashboard_bundle(run_dir)
            log(f"Dashboard bundle written to {run_dir / 'dashboard_bundle.json'}.")
            return run_dir

        summary.reports_total = len(bug_report_paths)
        log(f"Verification starting for {len(bug_report_paths)} report(s).")
        bug_reports = [
            BugReportV1.model_validate(read_json(path)) for path in bug_report_paths
        ]
        write_run_state(
            run_dir=run_dir,
            run_id=run_id,
            status=RunStatus.RUNNING,
            stage=RunStage.VERIFICATION,
            started_at=started_at,
            completed_at=None,
            summary=summary,
        )
        fix_task_paths: list[Path] = []
        expected_source_paths = resolve_paths(config.verifier.expected_behavior_sources)
        for index, bug_report_path in enumerate(bug_report_paths, start=1):
            current_report = bug_reports[index - 1]
            verifier_result = verify_to_files(
                bug_report_path=bug_report_path,
                output_dir=run_dir / "verifier" / f"report_{index:03d}",
                expected_source_paths=expected_source_paths,
                repo=config.repo,
                sandbox_root=config.sandbox_root,
                promotion_policy=config.promotion_policy,
                model=config.verifier.model,
                related_reports=[
                    report
                    for report in bug_reports
                    if report.report_id != current_report.report_id
                ],
            )
            decision = VerifierDecisionV1.model_validate(
                read_json(Path(str(verifier_result["decision_path"])))
            )
            log(
                "Verifier decision for "
                f"{current_report.report_id}: {decision.classification.value} "
                f"({decision.confidence:.2f})"
            )
            if decision.classification == VerifierClassification.CONFIRMED:
                summary.confirmed_total += 1
            elif decision.classification == VerifierClassification.INVALID:
                summary.invalid_total += 1
            elif decision.classification == VerifierClassification.DUPLICATE:
                summary.duplicate_total += 1

            fix_task_path = verifier_result.get("fix_task_path")
            if fix_task_path:
                fix_task_paths.append(Path(str(fix_task_path)))
                log(f"Fix task created: {fix_task_path}")

        if not fix_task_paths:
            log("No confirmed fix tasks. Building dashboard bundle.")
            write_dashboard_bundle(run_dir)
            log(f"Dashboard bundle written to {run_dir / 'dashboard_bundle.json'}.")
            return run_dir

        log(f"Fixing starting for {len(fix_task_paths)} task(s).")
        write_run_state(
            run_dir=run_dir,
            run_id=run_id,
            status=RunStatus.RUNNING,
            stage=RunStage.FIXING,
            started_at=started_at,
            completed_at=None,
            summary=summary,
        )
        for index, fix_task_path in enumerate(fix_task_paths, start=1):
            log(f"Fixing task {index}/{len(fix_task_paths)}: {fix_task_path}")
            fix_result = fix_to_file(
                fix_task_path,
                run_dir / "fixing" / f"task_{index:03d}",
                config.fixing.model,
            )
            if fix_result.promoted:
                summary.fixed_total += 1
                log(f"Fix task promoted successfully: {fix_result.result_id}")
            else:
                log(f"Fix task did not promote: {fix_result.status.value}")

        write_run_state(
            run_dir=run_dir,
            run_id=run_id,
            status=RunStatus.COMPLETED,
            stage=RunStage.COMPLETE,
            started_at=started_at,
            completed_at=utc_now(),
            summary=summary,
        )
        write_dashboard_bundle(run_dir)
        log(f"Run complete. Dashboard bundle written to {run_dir / 'dashboard_bundle.json'}.")
        return run_dir
    finally:
        log("Stopping app process.")
        app_process.terminate()
        try:
            app_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app_process.kill()
        if app_process.stdout:
            recent_output = app_process.stdout.read()
            if recent_output:
                log("App process output:")
                print(recent_output[-4000:], flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live adaptive healing workflow.")
    parser.add_argument("--mode", choices=["live"], default="live")
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "run_config.json")
    args = parser.parse_args()

    config = RunConfigV1.model_validate(read_json(args.config))
    run_dir = run_live(config)
    print(f"Run artifacts: {run_dir}")
    print(f"Dashboard bundle: {run_dir / 'dashboard_bundle.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
