from __future__ import annotations

import argparse
import json
import shutil
import shlex
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from shared.ai.gpt5_client import OpenAIJsonClient
from shared.contracts.models import (
    ArtifactRefV1,
    ErrorV1,
    FixResultV1,
    FixStatus,
    FixTaskV1,
    ModelConfigV1,
    TestStatus,
    TestSummaryV1,
)
from shared.io import read_json, write_json
from shared.logging import log
from shared.time import utc_now


IGNORED_COPY_DIRS = {
    ".git",
    ".venv",
    ".sandbox",
    "artifacts",
    "__pycache__",
    ".pytest_cache",
}


def ignore_workspace_items(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_COPY_DIRS}


def prepare_sandbox(task: FixTaskV1, root: Path) -> Path:
    sandbox_path = root / task.sandbox.path
    if sandbox_path.exists():
        log(f"Fixing agent: removing existing sandbox {sandbox_path}.")
        shutil.rmtree(sandbox_path)
    log(f"Fixing agent: creating sandbox at {sandbox_path}.")
    shutil.copytree(root, sandbox_path, ignore=ignore_workspace_items)
    return sandbox_path


def collect_context(sandbox_path: Path, task: FixTaskV1) -> dict[str, str]:
    files = [task.repo.entrypoint]
    tests_dir = sandbox_path / "tests"
    if tests_dir.exists():
        files.extend(str(path.relative_to(sandbox_path)) for path in sorted(tests_dir.rglob("test_*.py")))

    context: dict[str, str] = {}
    for relative_path in files:
        path = sandbox_path / relative_path
        if path.exists() and path.is_file():
            context[relative_path] = path.read_text()
    return context


def request_patch(
    task: FixTaskV1,
    context: dict[str, str],
    model: ModelConfigV1,
) -> dict[str, object]:
    log(f"Fixing agent: asking model {model.model_name} for patch.")
    client = OpenAIJsonClient(
        model=model.model_name,
        reasoning_effort=model.reasoning_effort,
    )
    instructions = (
        "You are the live fixing agent for a sandboxed Python/FastAPI repository. "
        "Fix only the confirmed bug. Do not hardcode the report. Preserve unrelated behavior. "
        "Return JSON only with full replacement contents for changed files."
    )
    prompt = json.dumps(
        {
            "fix_task": task.model_dump(mode="json"),
            "repository_context": context,
            "allowed_response_shape": {
                "summary": "short summary",
                "changed_files": [
                    {
                        "path": "relative file path",
                        "content": "full replacement file content"
                    }
                ]
            },
        },
        indent=2,
    )
    response = client.create_json(instructions=instructions, prompt=prompt)
    log("Fixing agent: model patch response received.")
    return response


def apply_model_changes(sandbox_path: Path, patch_response: dict[str, object]) -> list[str]:
    changed_files = patch_response.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        raise ValueError("Model patch response must include changed_files")

    paths: list[str] = []
    for item in changed_files:
        if not isinstance(item, dict):
            raise ValueError("Each changed_files item must be an object")
        relative_path = Path(str(item["path"]))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Unsafe changed file path: {relative_path}")
        target = sandbox_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(item["content"]))
        paths.append(str(relative_path))
    return paths


def run_tests(sandbox_path: Path, command: str) -> tuple[TestSummaryV1, str]:
    log(f"Fixing agent: running tests in sandbox: {command}")
    started = time.monotonic()
    completed = subprocess.run(
        shlex.split(command),
        cwd=sandbox_path,
        text=True,
        capture_output=True,
        check=False,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    output = completed.stdout + "\n" + completed.stderr
    status = TestStatus.PASSED if completed.returncode == 0 else TestStatus.FAILED
    log(f"Fixing agent: tests {status.value} in {duration_ms} ms.")
    return (
        TestSummaryV1(
            command=command,
            status=status,
            passed=0,
            failed=0 if status == TestStatus.PASSED else 1,
            duration_ms=duration_ms,
            report_artifact_id=None,
        ),
        output,
    )


def promote_changes(root: Path, sandbox_path: Path, changed_files: list[str], task: FixTaskV1) -> None:
    if task.promotion_policy.target_file not in changed_files:
        raise ValueError(
            f"Promotion requires {task.promotion_policy.target_file} in changed files."
        )
    for relative in changed_files:
        if not (relative.startswith("app/") or relative.startswith("tests/")):
            raise ValueError(f"Refusing to promote unsupported path: {relative}")
        source = sandbox_path / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def fix_to_file(
    task_path: Path,
    output_dir: Path,
    model: ModelConfigV1 | None = None,
) -> FixResultV1:
    root = Path.cwd()
    task = FixTaskV1.model_validate(read_json(task_path))
    model = model or ModelConfigV1(reasoning_effort="high")
    log(f"Fixing agent: loaded task {task.task_id} from {task_path}.")
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    started = time.monotonic()
    changed_files: list[str] = []
    artifacts: list[ArtifactRefV1] = []
    error = None
    promoted = False
    summary = "Fix attempt did not complete."
    tests = TestSummaryV1(
        command=task.repo.test_command,
        status=TestStatus.NOT_RUN,
        passed=0,
        failed=0,
        duration_ms=0,
        report_artifact_id=None,
    )

    try:
        sandbox_path = prepare_sandbox(task, root)
        context = collect_context(sandbox_path, task)
        log(f"Fixing agent: collected {len(context)} context file(s).")
        patch_response = request_patch(task, context, model)
        summary = str(patch_response.get("summary", "Applied model-proposed changes."))
        changed_files = apply_model_changes(sandbox_path, patch_response)
        log(f"Fixing agent: model changed {len(changed_files)} file(s): {changed_files}.")

        tests, test_output = run_tests(sandbox_path, task.repo.test_command)
        test_report_path = output_dir / "test_report.txt"
        test_report_path.write_text(test_output)
        artifacts.append(
            ArtifactRefV1(
                artifact_id=f"art_{uuid4().hex[:10]}",
                type="test_report",
                uri=str(test_report_path),
                mime_type="text/plain",
                created_at=utc_now(),
                sha256=None,
                metadata={},
            )
        )
        tests.report_artifact_id = artifacts[-1].artifact_id

        if tests.status == TestStatus.PASSED:
            promote_changes(root, sandbox_path, changed_files, task)
            promoted = True
            status = FixStatus.FIXED
            log(f"Fixing agent: promoted task {task.task_id}.")
        else:
            status = FixStatus.FAILED
            log(f"Fixing agent: not promoting task {task.task_id}; tests failed.")
    except Exception as exc:
        status = FixStatus.FAILED
        log(f"Fixing agent: task {task.task_id} failed with {exc.__class__.__name__}: {exc}")
        error = ErrorV1(
            code=exc.__class__.__name__,
            message=str(exc),
            recoverable=True,
            details={},
        )

    result = FixResultV1(
        result_id=f"fixres_{uuid4().hex[:10]}",
        task_id=task.task_id,
        run_id=task.run_id,
        canonical_bug_id=task.canonical_bug_id,
        status=status,
        started_at=started_at,
        completed_at=utc_now(),
        duration_ms=int((time.monotonic() - started) * 1000),
        summary=summary,
        changed_files=changed_files,
        artifacts=artifacts,
        tests=tests,
        promoted=promoted,
        error=error,
        metadata={},
    )
    write_json(output_dir / "fix_result.json", result)
    log(f"Fixing agent: result written to {output_dir / 'fix_result.json'}.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live model-backed fixing agent.")
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5")
    parser.add_argument(
        "--reasoning-effort",
        choices=["minimal", "low", "medium", "high", "none"],
        default="high",
    )
    args = parser.parse_args()
    reasoning_effort = None if args.reasoning_effort == "none" else args.reasoning_effort

    result = fix_to_file(
        args.task,
        args.output_dir,
        ModelConfigV1(model_name=args.model, reasoning_effort=reasoning_effort),
    )
    print(result.model_dump_json(indent=2))
    return 0 if result.status == FixStatus.FIXED else 1


if __name__ == "__main__":
    raise SystemExit(main())
