from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from shared.ai.gpt5_client import OpenAIJsonClient
from shared.contracts.models import (
    ArtifactRefV1,
    ErrorV1,
    EventSource,
    EventStatus,
    FixResultV1,
    FixStatus,
    FixTaskV1,
    ModelConfigV1,
    TestStatus,
    TestSummaryV1,
    TranscriptEventV1,
)
from shared.io import append_jsonl, read_json, write_json
from shared.logging import log
from shared.time import utc_now


CODEX_FIXER_MODEL = "gpt-5.3-codex"
RAW_GPT_FIXER_MODEL = "gpt-5.5"
RAW_GPT_FIXER_REASONING_EFFORT = "high"
OPENAI_API_KEY_ENV_NAMES = ("OPENAI_API_KEY", "OPENAIKEY", "OPENAI_KEY")
MAX_FIX_ATTEMPTS = 3
CODEX_API_KEY_LOGIN_TIMEOUT_SECONDS = 30
CODEX_EXEC_TIMEOUT_SECONDS = 240
RAW_GPT_FIXER_TIMEOUT_SECONDS = 240
TEST_TIMEOUT_SECONDS = 60
CONTRACT_VALIDATION_TIMEOUT_SECONDS = 30
MAX_HISTORY_TEXT_CHARS = 8000
MAX_PROMPT_FILE_CHARS = 50000
MAX_REPOSITORY_CONTEXT_CHARS = 140000
CODEX_WRITE_BLOCKED_MARKERS = (
    "read-only sandbox",
    "writing is blocked",
    "write is blocked",
    "read permission",
    "permission denied",
    "tool reads/writes",
    "tools are blocked",
    "file editing tools are blocked",
    "could not inspect",
    "could not modify",
    "unable to edit",
    "no changed files",
)

IGNORED_COPY_DIRS = {
    ".git",
    ".venv",
    ".sandbox",
    "artifacts",
    "__pycache__",
    ".pytest_cache",
}


def truncate_text(value: str, limit: int = MAX_HISTORY_TEXT_CHARS) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + f"\n...[truncated {len(value) - limit} chars]"


def ignore_workspace_items(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in IGNORED_COPY_DIRS}


def record_event(
    *,
    transcript_path: Path,
    task: FixTaskV1,
    event_type: str,
    status: EventStatus,
    summary: str,
    duration_ms: int,
    artifacts: list[ArtifactRefV1] | None = None,
    payload: dict[str, object] | None = None,
    error: ErrorV1 | None = None,
) -> TranscriptEventV1:
    event = TranscriptEventV1(
        event_id=f"evt_{uuid4().hex[:10]}",
        run_id=task.run_id,
        source=EventSource.FIXING_AGENT,
        source_id=task.task_id,
        event_type=event_type,
        status=status,
        timestamp=utc_now(),
        duration_ms=duration_ms,
        summary=summary,
        artifacts=artifacts or [],
        payload=payload or {},
        error=error,
    )
    append_jsonl(transcript_path, event)
    return event


def prepare_sandbox(task: FixTaskV1, root: Path) -> Path:
    sandbox_path = root / task.sandbox.path
    if sandbox_path.exists():
        log(f"Fixing agent: removing existing sandbox {sandbox_path}.")
        shutil.rmtree(sandbox_path)
    log(f"Fixing agent: creating sandbox at {sandbox_path}.")
    shutil.copytree(root, sandbox_path, ignore=ignore_workspace_items)
    return sandbox_path


def normalize_relative_path(raw_path: object) -> str:
    relative_path = Path(str(raw_path))
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError(f"Unsafe file path: {relative_path}")
    return relative_path.as_posix()


def is_promotable_path(relative_path: str) -> bool:
    return relative_path.startswith("app/") or relative_path.startswith("tests/")


def write_sandbox_file(sandbox_path: Path, raw_path: object, content: object) -> str:
    relative_path = normalize_relative_path(raw_path)
    if not is_promotable_path(relative_path):
        raise ValueError(f"Refusing to write unsupported path: {relative_path}")
    target = sandbox_path / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(content))
    return relative_path


def parse_pytest_counts(output: str, status: TestStatus) -> tuple[int, int]:
    passed = 0
    failed = 0
    for token, target in (("passed", "passed"), ("failed", "failed"), ("error", "failed"), ("errors", "failed")):
        matches = [int(match) for match in re.findall(rf"(\d+)\s+{token}\b", output)]
        if target == "passed":
            passed += sum(matches)
        else:
            failed += sum(matches)
    if status == TestStatus.FAILED and failed == 0:
        failed = 1
    return passed, failed


def run_tests(sandbox_path: Path, command: str) -> tuple[TestSummaryV1, str]:
    log(f"Fixing agent: running tests in sandbox: {command}")
    started = time.monotonic()
    try:
        completed = subprocess.run(
            shlex.split(command),
            cwd=sandbox_path,
            text=True,
            capture_output=True,
            check=False,
            timeout=TEST_TIMEOUT_SECONDS,
        )
        output = completed.stdout + "\n" + completed.stderr
        status = TestStatus.PASSED if completed.returncode == 0 else TestStatus.FAILED
    except subprocess.TimeoutExpired as exc:
        output = (
            f"Test command timed out after {TEST_TIMEOUT_SECONDS} seconds.\n"
            f"{exc.stdout or ''}\n{exc.stderr or ''}"
        )
        status = TestStatus.FAILED
    duration_ms = int((time.monotonic() - started) * 1000)
    passed, failed = parse_pytest_counts(output, status)
    log(f"Fixing agent: tests {status.value} in {duration_ms} ms.")
    return (
        TestSummaryV1(
            command=command,
            status=status,
            passed=passed,
            failed=failed,
            duration_ms=duration_ms,
            report_artifact_id=None,
        ),
        output,
    )


def run_contract_validation(sandbox_path: Path) -> tuple[bool, str, int]:
    commands = [
        [sys.executable, "-m", "shared.contracts.validate", "fixtures/contracts"],
        [sys.executable, "-m", "shared.contracts.validate", "configs/run_config.json"],
    ]
    started = time.monotonic()
    outputs = []
    for command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=sandbox_path,
                text=True,
                capture_output=True,
                check=False,
                timeout=CONTRACT_VALIDATION_TIMEOUT_SECONDS,
            )
            outputs.append("$ " + " ".join(command))
            outputs.append(completed.stdout + completed.stderr)
            if completed.returncode != 0:
                return False, "\n".join(outputs), int((time.monotonic() - started) * 1000)
        except subprocess.TimeoutExpired as exc:
            outputs.append("$ " + " ".join(command))
            outputs.append(
                f"Contract validation timed out after {CONTRACT_VALIDATION_TIMEOUT_SECONDS} seconds.\n"
                f"{exc.stdout or ''}\n{exc.stderr or ''}"
            )
            return False, "\n".join(outputs), int((time.monotonic() - started) * 1000)
    return True, "\n".join(outputs), int((time.monotonic() - started) * 1000)


def write_final_test_report_artifact(
    output_dir: Path,
    test_output: str,
    tests: TestSummaryV1,
    artifacts: list[ArtifactRefV1],
    fix_attempt: int,
) -> Path:
    test_report_path = output_dir / "test_report.txt"
    test_report_path.write_text(test_output)
    artifact = ArtifactRefV1(
        artifact_id=f"art_{uuid4().hex[:10]}",
        type="test_report",
        uri=str(test_report_path),
        mime_type="text/plain",
        created_at=utc_now(),
        sha256=None,
        metadata={"fix_attempt": fix_attempt},
    )
    artifacts.append(artifact)
    tests.report_artifact_id = artifact.artifact_id
    return test_report_path


def iter_promotable_files(sandbox_path: Path) -> list[Path]:
    files: list[Path] = []
    for directory_name in ("app", "tests"):
        directory = sandbox_path / directory_name
        if directory.exists():
            files.extend(path for path in directory.rglob("*") if path.is_file())
    return sorted(files)


def sha256_bytes(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_promotable_files(sandbox_path: Path) -> dict[str, str]:
    return {
        path.relative_to(sandbox_path).as_posix(): sha256_bytes(path)
        for path in iter_promotable_files(sandbox_path)
    }


def detect_changed_files(sandbox_path: Path, before: dict[str, str]) -> list[str]:
    after = snapshot_promotable_files(sandbox_path)
    changed = [
        relative_path
        for relative_path, digest in after.items()
        if before.get(relative_path) != digest
    ]
    deleted = [relative_path for relative_path in before if relative_path not in after]
    if deleted:
        raise ValueError(f"Codex deleted promotable files: {deleted}")
    return sorted(changed)


def repository_context_for_prompt(sandbox_path: Path, task: FixTaskV1) -> dict[str, str]:
    candidate_paths = [
        task.repo.entrypoint,
        "app/buggy_main_seed.py",
        "configs/run_config.json",
        "tests/test_shop_smoke.py",
        "tests/test_group_buy_wiring.py",
    ]
    context: dict[str, str] = {}
    used_chars = 0
    for raw_path in candidate_paths:
        try:
            relative_path = normalize_relative_path(raw_path)
        except ValueError:
            continue
        path = sandbox_path / relative_path
        if not path.exists() or not path.is_file():
            continue
        content = path.read_text()
        if len(content) > MAX_PROMPT_FILE_CHARS:
            content = truncate_text(content, MAX_PROMPT_FILE_CHARS)
        if used_chars + len(content) > MAX_REPOSITORY_CONTEXT_CHARS:
            remaining_chars = MAX_REPOSITORY_CONTEXT_CHARS - used_chars
            if remaining_chars <= 0:
                break
            content = truncate_text(content, remaining_chars)
        context[relative_path] = content
        used_chars += len(content)
    return context


def build_codex_prompt(
    task: FixTaskV1,
    sandbox_path: Path,
    validation_feedback: str | None = None,
) -> str:
    return (
        "You are the real Codex fixing agent for this sandboxed repository.\n"
        "Use your built-in file reading, file editing, shell, and completion tools to fix the confirmed bug.\n"
        "Do not hardcode the report. Preserve unrelated behavior. Keep edits scoped to app/ and tests/.\n"
        "The orchestrator will run tests, contract validation, and promotion after you finish.\n"
        "Before finishing, inspect the relevant files and make the smallest correct code change.\n"
        "Do not edit files outside app/ or tests/.\n"
        "A bounded repository context is included below because nested tool reads/writes may be blocked.\n"
        "If tools are blocked, use the included file contents and return full replacement content.\n"
        "When done, respond with JSON only. If your file editing tools succeeded, use this shape:\n"
        '{"summary":"short summary","changed_files":["relative/path.py"]}\n'
        "If file editing tools are blocked by policy, return full replacement content instead:\n"
        '{"summary":"short summary","changed_files":[{"path":"relative/path.py","content":"full file content"}]}\n\n'
        "Fix task JSON:\n"
        f"{json.dumps(task.model_dump(mode='json'), indent=2)}\n"
        "Previous validation feedback:\n"
        f"{validation_feedback or 'None'}\n"
        "Repository context JSON:\n"
        f"{json.dumps(repository_context_for_prompt(sandbox_path, task), indent=2)}\n"
    )


def build_raw_gpt_patch_prompt(
    task: FixTaskV1,
    sandbox_path: Path,
    *,
    validation_feedback: str | None,
    codex_summary: str,
) -> str:
    return (
        "Codex exec was attempted first, but its file tools appear to be blocked.\n"
        "Generate a genuine source patch from the confirmed bug report and repository context.\n"
        "Do not hardcode success. Preserve unrelated behavior and keep edits scoped to app/ and tests/.\n"
        "Return JSON only with this exact shape:\n"
        '{"summary":"short summary","changed_files":[{"path":"relative/path.py","content":"full file content"}]}\n\n'
        "Every changed_files item must include full replacement content for the file.\n"
        "Do not return diffs, markdown, commentary, or paths outside app/ or tests/.\n\n"
        "Fix task JSON:\n"
        f"{json.dumps(task.model_dump(mode='json'), indent=2)}\n"
        "Codex blocked/failed summary:\n"
        f"{truncate_text(codex_summary, 12000)}\n"
        "Previous validation feedback:\n"
        f"{validation_feedback or 'None'}\n"
        "Repository context JSON:\n"
        f"{json.dumps(repository_context_for_prompt(sandbox_path, task), indent=2)}\n"
    )


def parse_codex_last_message(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {"summary": path.read_text().strip()}


def apply_codex_reported_file_contents(sandbox_path: Path, final_message: dict[str, object]) -> list[str]:
    raw_changes = final_message.get("changed_files")
    if not isinstance(raw_changes, list):
        raw_changes = final_message.get("proposed_changes")
    if not isinstance(raw_changes, list):
        return []

    applied_paths: list[str] = []
    for item in raw_changes:
        if not isinstance(item, dict):
            continue
        if "path" not in item or "content" not in item:
            continue
        applied_paths.append(write_sandbox_file(sandbox_path, item["path"], item["content"]))
    return sorted(set(applied_paths))


def resolve_codex_executable() -> str:
    resolved = shutil.which("codex") or shutil.which("codex.exe")
    if resolved:
        return resolved

    extension_root = Path.home() / ".vscode" / "extensions"
    candidates = sorted(
        extension_root.glob("openai.chatgpt-*/bin/windows-*/codex.exe"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return str(candidates[0])

    raise FileNotFoundError(
        "Could not find Codex CLI executable. Ensure codex is on PATH or installed via the OpenAI extension."
    )


def get_openai_api_key() -> tuple[str, str]:
    for env_name in OPENAI_API_KEY_ENV_NAMES:
        value = os.environ.get(env_name, "").strip()
        if value:
            return value, env_name
    raise RuntimeError(
        "Fixing agent requires an OpenAI API key in OPENAI_API_KEY or OPENAIKEY for Codex exec."
    )


def ensure_openai_api_key_env() -> str:
    api_key, api_key_env_name = get_openai_api_key()
    if not os.environ.get("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = api_key
    return api_key_env_name


def build_codex_api_key_env(codex_home: Path, api_key: str) -> dict[str, str]:
    env = os.environ.copy()
    env["CODEX_HOME"] = str(codex_home)
    env["OPENAI_API_KEY"] = api_key
    return env


def login_codex_with_api_key(
    *,
    codex_executable: str,
    codex_home: Path,
    sandbox_path: Path,
    api_key: str,
) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    sandbox_config_path = sandbox_path.as_posix().replace("\\", "\\\\").replace("'", "\\'")
    (codex_home / "config.toml").write_text(
        "\n".join(
            [
                'preferred_auth_method = "apikey"',
                'approval_policy = "never"',
                'sandbox_mode = "workspace-write"',
                "",
                f"[projects.'{sandbox_config_path}']",
                'trust_level = "trusted"',
                "",
            ]
        )
    )
    completed = subprocess.run(
        [codex_executable, "login", "--with-api-key"],
        input=api_key + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=CODEX_API_KEY_LOGIN_TIMEOUT_SECONDS,
        env=build_codex_api_key_env(codex_home, api_key),
    )
    if completed.returncode != 0:
        output = completed.stdout + completed.stderr
        raise RuntimeError(f"codex API-key login failed: {truncate_text(output, 1200)}")


def codex_model_attempts(model: ModelConfigV1) -> list[ModelConfigV1]:
    return [
        ModelConfigV1(
            provider=model.provider,
            model_name=model.model_name,
            mode=model.mode,
            reasoning_effort=model.reasoning_effort,
        )
    ]


def safe_model_filename(model_name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", model_name)


def codex_transcript_artifact(
    transcript_path: Path,
    model: ModelConfigV1,
    duration_ms: int,
    model_attempt: int,
) -> ArtifactRefV1:
    return ArtifactRefV1(
        artifact_id=f"art_{uuid4().hex[:10]}",
        type="text_log",
        uri=str(transcript_path),
        mime_type="application/jsonl",
        created_at=utc_now(),
        sha256=None,
        metadata={
            "kind": "codex_exec_events",
            "model_name": model.model_name,
            "model_attempt": model_attempt,
            "duration_ms": duration_ms,
        },
    )


def raw_gpt_response_artifact(
    response_path: Path,
    duration_ms: int,
    fix_attempt: int,
) -> ArtifactRefV1:
    return ArtifactRefV1(
        artifact_id=f"art_{uuid4().hex[:10]}",
        type="text_log",
        uri=str(response_path),
        mime_type="application/json",
        created_at=utc_now(),
        sha256=None,
        metadata={
            "kind": "raw_gpt_fallback_response",
            "model_name": RAW_GPT_FIXER_MODEL,
            "reasoning_effort": RAW_GPT_FIXER_REASONING_EFFORT,
            "fix_attempt": fix_attempt,
            "duration_ms": duration_ms,
        },
    )


def should_run_raw_gpt_fallback(changed_files: list[str], codex_output: str) -> bool:
    if changed_files:
        return False
    normalized = codex_output.lower()
    return any(marker in normalized for marker in CODEX_WRITE_BLOCKED_MARKERS)


def run_raw_gpt_fallback(
    *,
    task: FixTaskV1,
    sandbox_path: Path,
    output_dir: Path,
    validation_feedback: str | None,
    codex_summary: str,
    fix_attempt: int,
) -> tuple[list[str], str, ArtifactRefV1]:
    transcript_path = output_dir / "transcript.jsonl"
    started = time.monotonic()
    before = snapshot_promotable_files(sandbox_path)
    api_key_env_name = ensure_openai_api_key_env()
    response_path = output_dir / f"raw_gpt_fallback_{fix_attempt:03d}.json"

    record_event(
        transcript_path=transcript_path,
        task=task,
        event_type="raw_gpt_fallback_started",
        status=EventStatus.STARTED,
        summary=(
            f"Started raw OpenAI fallback with {RAW_GPT_FIXER_MODEL} after Codex "
            "returned no writable changes."
        ),
        duration_ms=0,
        payload={
            "fix_attempt": fix_attempt,
            "model_name": RAW_GPT_FIXER_MODEL,
            "reasoning_effort": RAW_GPT_FIXER_REASONING_EFFORT,
            "timeout_seconds": RAW_GPT_FIXER_TIMEOUT_SECONDS,
            "api_key_env_name": api_key_env_name,
            "trigger": "codex_no_changed_files_write_blocked",
        },
    )

    try:
        client = OpenAIJsonClient(
            model=RAW_GPT_FIXER_MODEL,
            reasoning_effort=RAW_GPT_FIXER_REASONING_EFFORT,
            timeout_seconds=RAW_GPT_FIXER_TIMEOUT_SECONDS,
        )
        response = client.create_json(
            instructions=(
                "You are a raw OpenAI fallback fixer. Produce full replacement file "
                "contents as strict JSON so the outer fixer can write the files."
            ),
            prompt=build_raw_gpt_patch_prompt(
                task,
                sandbox_path,
                validation_feedback=validation_feedback,
                codex_summary=codex_summary,
            ),
        )
        write_json(response_path, response)
        applied_paths = apply_codex_reported_file_contents(sandbox_path, response)
        changed_files = detect_changed_files(sandbox_path, before)
        summary = str(response.get("summary") or "Raw GPT fallback generated a patch.")
        duration_ms = int((time.monotonic() - started) * 1000)
        artifact = raw_gpt_response_artifact(response_path, duration_ms, fix_attempt)
        record_event(
            transcript_path=transcript_path,
            task=task,
            event_type="raw_gpt_fallback_completed",
            status=EventStatus.COMPLETED,
            summary=summary,
            duration_ms=duration_ms,
            artifacts=[artifact],
            payload={
                "fix_attempt": fix_attempt,
                "model_name": RAW_GPT_FIXER_MODEL,
                "reasoning_effort": RAW_GPT_FIXER_REASONING_EFFORT,
                "applied_paths": applied_paths,
                "changed_files": changed_files,
            },
        )
        return changed_files, summary, artifact
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        record_event(
            transcript_path=transcript_path,
            task=task,
            event_type="raw_gpt_fallback_failed",
            status=EventStatus.FAILED,
            summary=f"Raw GPT fallback failed: {exc}",
            duration_ms=duration_ms,
            error=ErrorV1(
                code=exc.__class__.__name__,
                message=str(exc),
                recoverable=True,
                details={
                    "model_name": RAW_GPT_FIXER_MODEL,
                    "reasoning_effort": RAW_GPT_FIXER_REASONING_EFFORT,
                    "fix_attempt": fix_attempt,
                },
            ),
        )
        raise


def run_codex_exec(
    *,
    task: FixTaskV1,
    sandbox_path: Path,
    output_dir: Path,
    model: ModelConfigV1,
    validation_feedback: str | None = None,
) -> tuple[list[str], str, ArtifactRefV1]:
    prompt = build_codex_prompt(task, sandbox_path, validation_feedback)
    codex_executable = resolve_codex_executable()
    api_key, api_key_env_name = get_openai_api_key()
    model_attempts = codex_model_attempts(model)
    before = snapshot_promotable_files(sandbox_path)

    with tempfile.TemporaryDirectory(prefix="dywa-codex-api-") as codex_home_raw:
        codex_home = Path(codex_home_raw)
        login_codex_with_api_key(
            codex_executable=codex_executable,
            codex_home=codex_home,
            sandbox_path=sandbox_path,
            api_key=api_key,
        )
        codex_env = build_codex_api_key_env(codex_home, api_key)

        record_event(
            transcript_path=output_dir / "transcript.jsonl",
            task=task,
            event_type="codex_api_key_auth_prepared",
            status=EventStatus.COMPLETED,
            summary="Prepared temporary API-key Codex auth for fixer subprocess.",
            duration_ms=0,
            payload={
                "api_key_env_name": api_key_env_name,
                "codex_home": str(codex_home),
                "codex_home_cleanup": "temporary_directory",
            },
        )

        for model_attempt, active_model in enumerate(model_attempts, start=1):
            model_suffix = safe_model_filename(active_model.model_name)
            transcript_path = output_dir / f"codex_exec_events_{model_attempt:02d}_{model_suffix}.jsonl"
            last_message_path = output_dir / f"codex_last_message_{model_attempt:02d}_{model_suffix}.json"
            command = build_codex_command(
                codex_executable=codex_executable,
                sandbox_path=sandbox_path,
                model=active_model,
                last_message_path=last_message_path,
            )

            started = time.monotonic()
            record_event(
                transcript_path=output_dir / "transcript.jsonl",
                task=task,
                event_type="codex_exec_started",
                status=EventStatus.STARTED,
                summary=f"Started real Codex exec with {active_model.model_name} using API-key auth.",
                duration_ms=0,
                payload={
                    "command": command,
                    "timeout_seconds": CODEX_EXEC_TIMEOUT_SECONDS,
                    "sandbox_path": str(sandbox_path),
                    "requested_model_name": model.model_name,
                    "model_name": active_model.model_name,
                    "model_attempt": model_attempt,
                    "model_attempts_total": len(model_attempts),
                    "auth_mode": "api_key",
                    "api_key_env_name": api_key_env_name,
                },
            )

            try:
                completed = subprocess.run(
                    command,
                    cwd=sandbox_path,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=CODEX_EXEC_TIMEOUT_SECONDS,
                    env=codex_env,
                )
                output = completed.stdout + completed.stderr
                transcript_path.write_text(output)
                duration_ms = int((time.monotonic() - started) * 1000)
                if completed.returncode != 0:
                    artifact = codex_transcript_artifact(
                        transcript_path,
                        active_model,
                        duration_ms,
                        model_attempt,
                    )
                    message = f"codex exec exited with {completed.returncode}: {truncate_text(output, 1200)}"
                    record_event(
                        transcript_path=output_dir / "transcript.jsonl",
                        task=task,
                        event_type="codex_exec_failed",
                        status=EventStatus.FAILED,
                        summary=message,
                        duration_ms=duration_ms,
                        artifacts=[artifact],
                        error=ErrorV1(
                            code="codex_exec_failed",
                            message=message,
                            recoverable=model_attempt < len(model_attempts),
                            details={"model_name": active_model.model_name, "auth_mode": "api_key"},
                        ),
                    )
                    raise RuntimeError(message)
            except subprocess.TimeoutExpired as exc:
                output = (
                    f"Codex exec timed out after {CODEX_EXEC_TIMEOUT_SECONDS} seconds.\n"
                    f"{exc.stdout or ''}\n{exc.stderr or ''}"
                )
                transcript_path.write_text(output)
                duration_ms = int((time.monotonic() - started) * 1000)
                artifact = codex_transcript_artifact(
                    transcript_path,
                    active_model,
                    duration_ms,
                    model_attempt,
                )
                record_event(
                    transcript_path=output_dir / "transcript.jsonl",
                    task=task,
                    event_type="codex_exec_failed",
                    status=EventStatus.FAILED,
                    summary=f"Codex exec timed out with {active_model.model_name}.",
                    duration_ms=duration_ms,
                    artifacts=[artifact],
                    error=ErrorV1(
                        code="codex_exec_timeout",
                        message=truncate_text(output, 1200),
                        recoverable=False,
                        details={"model_name": active_model.model_name, "auth_mode": "api_key"},
                    ),
                )
                raise TimeoutError(output) from exc

            final_message = parse_codex_last_message(last_message_path)
            applied_reported_paths = apply_codex_reported_file_contents(sandbox_path, final_message)
            if applied_reported_paths:
                record_event(
                    transcript_path=output_dir / "transcript.jsonl",
                    task=task,
                    event_type="codex_reported_file_contents_applied",
                    status=EventStatus.COMPLETED,
                    summary="Applied full replacement file content returned by Codex.",
                    duration_ms=0,
                    payload={
                        "changed_files": applied_reported_paths,
                        "reason": "codex_tool_writes_unavailable",
                    },
                )
            changed_files = detect_changed_files(sandbox_path, before)
            summary = str(final_message.get("summary") or "Codex completed the fix attempt.")
            duration_ms = int((time.monotonic() - started) * 1000)
            artifact = codex_transcript_artifact(
                transcript_path,
                active_model,
                duration_ms,
                model_attempt,
            )
            record_event(
                transcript_path=output_dir / "transcript.jsonl",
                task=task,
                event_type="codex_exec_completed",
                status=EventStatus.COMPLETED,
                summary=summary,
                duration_ms=duration_ms,
                artifacts=[artifact],
                payload={
                    "changed_files": changed_files,
                    "last_message": final_message,
                    "requested_model_name": model.model_name,
                    "model_name": active_model.model_name,
                    "model_attempt": model_attempt,
                    "auth_mode": "api_key",
                    "api_key_env_name": api_key_env_name,
                },
            )
            return changed_files, summary, artifact

    raise RuntimeError("codex exec did not run any model attempts")


def build_codex_command(
    *,
    codex_executable: str,
    sandbox_path: Path,
    model: ModelConfigV1,
    last_message_path: Path,
) -> list[str]:
    return [
        codex_executable,
        "exec",
        "-c",
        'preferred_auth_method="apikey"',
        "-c",
        'approval_policy="never"',
        "-c",
        'sandbox_mode="workspace-write"',
        "--json",
        "--skip-git-repo-check",
        "--ignore-rules",
        "-C",
        str(sandbox_path),
        "-m",
        model.model_name,
        "-s",
        "workspace-write",
        "--color",
        "never",
        "-o",
        str(last_message_path),
        "-",
    ]


def promote_changes(root: Path, sandbox_path: Path, changed_files: list[str], task: FixTaskV1) -> None:
    if task.promotion_policy.target_file not in changed_files:
        raise ValueError(
            f"Promotion requires {task.promotion_policy.target_file} in changed files."
        )
    for relative in changed_files:
        relative = normalize_relative_path(relative)
        if not is_promotable_path(relative):
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
    model = model or ModelConfigV1(model_name=CODEX_FIXER_MODEL, reasoning_effort="high")
    log(f"Fixing agent: loaded task {task.task_id} from {task_path}.")
    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "transcript.jsonl"
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
        record_event(
            transcript_path=transcript_path,
            task=task,
            event_type="fixing_started",
            status=EventStatus.STARTED,
            summary=f"Started fixing task {task.task_id} with {model.model_name}.",
            duration_ms=0,
            payload={
                "model": model.model_dump(mode="json"),
                "task_path": str(task_path),
                "output_dir": str(output_dir),
                "retry_policy": {
                    "codex_exec_timeout_seconds": CODEX_EXEC_TIMEOUT_SECONDS,
                    "raw_gpt_fallback_timeout_seconds": RAW_GPT_FIXER_TIMEOUT_SECONDS,
                    "test_timeout_seconds": TEST_TIMEOUT_SECONDS,
                },
            },
        )
        sandbox_path = prepare_sandbox(task, root)
        record_event(
            transcript_path=transcript_path,
            task=task,
            event_type="sandbox_prepared",
            status=EventStatus.COMPLETED,
            summary=f"Prepared sandbox at {sandbox_path}.",
            duration_ms=0,
            payload={"sandbox_path": str(sandbox_path)},
        )

        final_test_output = ""
        last_fix_attempt = 0
        validation_feedback = None
        for fix_attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            last_fix_attempt = fix_attempt
            record_event(
                transcript_path=transcript_path,
                task=task,
                event_type="fix_attempt_started",
                status=EventStatus.STARTED,
                summary=f"Fix attempt {fix_attempt}/{MAX_FIX_ATTEMPTS} started.",
                duration_ms=0,
                payload={"fix_attempt": fix_attempt},
            )
            changed_files, summary, codex_artifact = run_codex_exec(
                task=task,
                sandbox_path=sandbox_path,
                output_dir=output_dir,
                model=model,
                validation_feedback=validation_feedback,
            )
            artifacts.append(codex_artifact)
            log(f"Fixing agent: Codex changed {len(changed_files)} file(s): {changed_files}.")
            codex_output = summary
            try:
                codex_output += "\n" + Path(codex_artifact.uri).read_text()
            except OSError:
                pass
            if should_run_raw_gpt_fallback(changed_files, codex_output):
                changed_files, summary, raw_gpt_artifact = run_raw_gpt_fallback(
                    task=task,
                    sandbox_path=sandbox_path,
                    output_dir=output_dir,
                    validation_feedback=validation_feedback,
                    codex_summary=codex_output,
                    fix_attempt=fix_attempt,
                )
                artifacts.append(raw_gpt_artifact)
                log(
                    "Fixing agent: raw GPT fallback changed "
                    f"{len(changed_files)} file(s): {changed_files}."
                )

            tests, test_output = run_tests(sandbox_path, task.repo.test_command)
            final_test_output = test_output
            attempt_report_path = output_dir / f"test_report_attempt_{fix_attempt:03d}.txt"
            attempt_report_path.write_text(test_output)
            attempt_artifact = ArtifactRefV1(
                artifact_id=f"art_{uuid4().hex[:10]}",
                type="test_report",
                uri=str(attempt_report_path),
                mime_type="text/plain",
                created_at=utc_now(),
                sha256=None,
                metadata={"fix_attempt": fix_attempt},
            )
            record_event(
                transcript_path=transcript_path,
                task=task,
                event_type="tests_run",
                status=EventStatus.COMPLETED if tests.status == TestStatus.PASSED else EventStatus.FAILED,
                summary=f"Tests {tests.status.value} on attempt {fix_attempt}.",
                duration_ms=tests.duration_ms,
                artifacts=[attempt_artifact],
                payload={"fix_attempt": fix_attempt, "tests": tests.model_dump(mode="json")},
            )

            contracts_ok = True
            contract_output = ""
            contract_duration_ms = 0
            if task.promotion_policy.requires_contract_validation:
                contracts_ok, contract_output, contract_duration_ms = run_contract_validation(sandbox_path)
                record_event(
                    transcript_path=transcript_path,
                    task=task,
                    event_type="contract_validation_run",
                    status=EventStatus.COMPLETED if contracts_ok else EventStatus.FAILED,
                    summary="Contract validation passed." if contracts_ok else "Contract validation failed.",
                    duration_ms=contract_duration_ms,
                    payload={
                        "fix_attempt": fix_attempt,
                        "output": truncate_text(contract_output),
                    },
                )

            if tests.status == TestStatus.PASSED and contracts_ok:
                test_report_path = write_final_test_report_artifact(
                    output_dir,
                    final_test_output,
                    tests,
                    artifacts,
                    fix_attempt,
                )
                promote_changes(root, sandbox_path, changed_files, task)
                promoted = True
                status = FixStatus.FIXED
                record_event(
                    transcript_path=transcript_path,
                    task=task,
                    event_type="changes_promoted",
                    status=EventStatus.COMPLETED,
                    summary=f"Promoted changes for task {task.task_id}.",
                    duration_ms=0,
                    payload={"changed_files": changed_files},
                )
                log(f"Fixing agent: promoted task {task.task_id}.")
                break

            record_event(
                transcript_path=transcript_path,
                task=task,
                event_type="fix_attempt_failed",
                status=EventStatus.FAILED,
                summary=f"Fix attempt {fix_attempt} failed validation gates.",
                duration_ms=0,
                payload={
                    "fix_attempt": fix_attempt,
                    "tests": tests.model_dump(mode="json"),
                    "test_output": truncate_text(test_output),
                    "contract_validation_passed": contracts_ok,
                    "contract_output": truncate_text(contract_output),
                },
            )
            status = FixStatus.FAILED
            validation_feedback = (
                f"Attempt {fix_attempt} did not pass validation.\n"
                f"Changed files: {changed_files}\n"
                f"Tests: {tests.model_dump(mode='json')}\n"
                f"Test output excerpt:\n{truncate_text(test_output, 12000)}\n"
                f"Contract validation passed: {contracts_ok}\n"
                f"Contract output excerpt:\n{truncate_text(contract_output, 4000)}"
            )
            log(f"Fixing agent: attempt {fix_attempt} did not pass all gates.")
    except Exception as exc:
        status = FixStatus.FAILED
        log(f"Fixing agent: task {task.task_id} failed with {exc.__class__.__name__}: {exc}")
        error = ErrorV1(
            code=exc.__class__.__name__,
            message=str(exc),
            recoverable=True,
            details={},
        )
        record_event(
            transcript_path=transcript_path,
            task=task,
            event_type="fixing_failed",
            status=EventStatus.FAILED,
            summary=f"Fixing task failed: {exc}",
            duration_ms=int((time.monotonic() - started) * 1000),
            error=error,
        )

    if tests.status != TestStatus.NOT_RUN and tests.report_artifact_id is None:
        write_final_test_report_artifact(
            output_dir,
            final_test_output,
            tests,
            artifacts,
            last_fix_attempt,
        )

    record_event(
        transcript_path=transcript_path,
        task=task,
        event_type="fixing_completed",
        status=EventStatus.COMPLETED if promoted else EventStatus.FAILED,
        summary=summary,
        duration_ms=int((time.monotonic() - started) * 1000),
        payload={
            "status": status.value,
            "changed_files": changed_files,
            "promoted": promoted,
        },
        error=error,
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
    parser.add_argument("--model", default=CODEX_FIXER_MODEL)
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
