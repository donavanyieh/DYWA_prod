import json

from shared.contracts.models import (
    ConfirmedBehaviorV1,
    EventStatus,
    FixTaskV1,
    ModelConfigV1,
    PersonaConfigV1,
    PersonaConstraintsV1,
    PromotionPolicyV1,
    RepoTargetV1,
    SandboxV1,
    TestStatus as ContractTestStatus,
    TranscriptEventV1,
    ViewportV1,
)
from shared.ai.gpt5_client import _extract_json
from agents.fixing.run import (
    build_codex_command,
    codex_model_attempts,
    detect_changed_files,
    is_chatgpt_account_model_unsupported,
    parse_pytest_counts,
    record_event,
    snapshot_promotable_files,
    write_sandbox_file,
)
from agents.personas.run import ask_for_valid_action, validate_action


def build_task() -> FixTaskV1:
    return FixTaskV1(
        task_id="fix_test_001",
        run_id="run_test_001",
        canonical_bug_id="bug_cart_total_quantity",
        created_at="2026-06-06T12:03:10Z",
        source_report_ids=["bugrep_test_001"],
        title="Cart total did not update after quantity changed",
        confirmed_behavior=ConfirmedBehaviorV1(
            observed="Cart quantity changed but total stayed unchanged.",
            expected="Cart total updates after quantity changes.",
        ),
        reproduction_steps=["Add item to cart.", "Increase quantity.", "Observe total."],
        evidence_artifacts=[],
        repo=RepoTargetV1(path=".", entrypoint="app/main.py", test_command="pytest"),
        sandbox=SandboxV1(mode="copy", path=".sandbox/run_test_001/fix_test_001"),
        promotion_policy=PromotionPolicyV1(
            target_file="app/main.py",
            requires_tests_green=True,
            requires_contract_validation=True,
        ),
        metadata={},
    )


def test_record_event_writes_dashboard_compatible_transcript(tmp_path) -> None:
    task = build_task()
    transcript_path = tmp_path / "transcript.jsonl"

    event = record_event(
        transcript_path=transcript_path,
        task=task,
        event_type="tool_read_file",
        status=EventStatus.COMPLETED,
        summary="Read app/main.py.",
        duration_ms=12,
        payload={"path": "app/main.py"},
    )

    saved = TranscriptEventV1.model_validate(json.loads(transcript_path.read_text()))
    assert saved == event
    assert saved.source == "fixing_agent"
    assert saved.source_id == task.task_id


def test_write_sandbox_file_rejects_non_promotable_paths(tmp_path) -> None:
    sandbox = tmp_path / "sandbox"

    relative_path = write_sandbox_file(sandbox, "app/main.py", "print('ok')\n")

    assert relative_path == "app/main.py"
    assert (sandbox / "app" / "main.py").read_text() == "print('ok')\n"

    try:
        write_sandbox_file(sandbox, "README.md", "nope")
    except ValueError as exc:
        assert "unsupported path" in str(exc)
    else:
        raise AssertionError("Expected unsupported path to be rejected")


def test_parse_pytest_counts_from_summary_line() -> None:
    output = "================ 3 passed, 1 warning in 0.16s ================\n"

    assert parse_pytest_counts(output, ContractTestStatus.PASSED) == (3, 0)
    assert parse_pytest_counts("1 failed, 2 passed", ContractTestStatus.FAILED) == (2, 1)


def test_extract_json_uses_first_valid_object_with_trailing_text() -> None:
    response = '{"tool": "read_file", "path": "app/main.py"}\n{"extra": "ignored"}'

    assert _extract_json(response) == {"tool": "read_file", "path": "app/main.py"}


def test_persona_click_button_requires_button_text() -> None:
    page_state = {"buttons": ["Add to cart"], "inputs": []}

    assert validate_action({"action": "click_button"}, page_state) == [
        "click_button requires button_text matching one visible button."
    ]
    assert validate_action(
        {"action": "click_button", "button_text": "Add to cart"},
        page_state,
    ) == []


def test_detect_changed_files_reports_promotable_edits(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    main_path = app_dir / "main.py"
    main_path.write_text("value = 1\n")
    before = snapshot_promotable_files(tmp_path)

    main_path.write_text("value = 2\n")

    assert detect_changed_files(tmp_path, before) == ["app/main.py"]


def test_codex_exec_command_uses_supported_noninteractive_flags(tmp_path) -> None:
    command = build_codex_command(
        codex_executable="codex.exe",
        sandbox_path=tmp_path,
        model=ModelConfigV1(model_name="gpt-5.3-codex", reasoning_effort="high"),
        last_message_path=tmp_path / "last.json",
    )

    assert command[:4] == ["codex.exe", "exec", "--json", "--skip-git-repo-check"]
    assert "-a" not in command
    assert "--color" in command
    assert command[-1] == "-"


def test_codex_model_attempts_fall_back_for_chatgpt_account() -> None:
    attempts = codex_model_attempts(
        ModelConfigV1(model_name="gpt-5.3-codex", reasoning_effort="high")
    )

    assert [attempt.model_name for attempt in attempts] == ["gpt-5.3-codex", "gpt-5-codex"]
    assert [attempt.reasoning_effort for attempt in attempts] == ["high", "high"]


def test_codex_unsupported_chatgpt_model_error_detected() -> None:
    output = (
        '{"type":"error","status":400,"error":{"type":"invalid_request_error",'
        '"message":"The \'gpt-5.3-codex\' model is not supported when using Codex with a ChatGPT account."}}'
    )

    assert is_chatgpt_account_model_unsupported(output)


def test_persona_action_parse_errors_fall_back_to_finish(tmp_path) -> None:
    class BrokenClient:
        def create_json(self, **_kwargs):
            raise ValueError("bad json")

    config = PersonaConfigV1(
        run_id="run_test_001",
        persona_id="persona_test",
        app_base_url="http://127.0.0.1:8765",
        goal="Test cart behavior.",
        traits={},
        constraints=PersonaConstraintsV1(
            max_duration_ms=1000,
            max_actions=1,
            viewport=ViewportV1(width=800, height=600),
        ),
        artifact_dir=str(tmp_path),
        model=ModelConfigV1(model_name="gpt-4o-mini", reasoning_effort=None),
    )
    screenshot = {
        "schema_version": "1.0.0",
        "artifact_id": "art_test",
        "type": "screenshot",
        "uri": str(tmp_path / "screen.png"),
        "mime_type": "image/png",
        "created_at": "2026-06-06T12:00:00Z",
        "sha256": None,
        "metadata": {},
    }

    action = ask_for_valid_action(
        client=BrokenClient(),
        config=config,
        page_state={"buttons": [], "inputs": []},
        screenshot=type("Screenshot", (), screenshot)(),
        history=[],
        max_attempts=2,
    )

    assert action["action"] == "finish"
    assert action["stop_reason"] == "no_useful_action"
