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
    CODEX_EXEC_TIMEOUT_SECONDS,
    RAW_GPT_FIXER_MODEL,
    RAW_GPT_FIXER_REASONING_EFFORT,
    RAW_GPT_FIXER_TIMEOUT_SECONDS,
    apply_codex_reported_file_contents,
    build_codex_prompt,
    build_codex_command,
    build_raw_gpt_patch_prompt,
    codex_model_attempts,
    combine_subprocess_output,
    detect_changed_files,
    ensure_openai_api_key_env,
    get_openai_api_key,
    parse_pytest_counts,
    record_event,
    should_run_raw_gpt_fallback,
    snapshot_promotable_files,
    write_sandbox_file,
)
from agents.personas.run import ask_for_valid_action, execute_action, validate_action


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


def test_combine_subprocess_output_handles_none_and_bytes() -> None:
    assert combine_subprocess_output(None, "stderr text") == "stderr text"
    assert combine_subprocess_output(b"stdout bytes", None) == "stdout bytes"
    assert combine_subprocess_output(None, None) == ""


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


def test_persona_click_button_rejects_disabled_button() -> None:
    page_state = {
        "buttons": ["Join Group Buy"],
        "button_details": [
            {"index": 0, "text": "Join Group Buy", "enabled": False, "disabled": True}
        ],
        "inputs": [],
    }

    errors = validate_action(
        {"action": "click_button", "button_text": "Join Group Buy"},
        page_state,
    )

    assert len(errors) == 1
    assert "visible but disabled" in errors[0]


def test_persona_execute_action_skips_disabled_button() -> None:
    class FakeLocator:
        clicked = False

        @property
        def first(self):
            return self

        def count(self):
            return 1

        def is_enabled(self, timeout=0):
            return False

        def click(self, timeout=0):
            self.clicked = True

    class FakePage:
        locator = FakeLocator()

        def get_by_role(self, role, name):
            assert role == "button"
            assert name == "Join Group Buy"
            return self.locator

    page = FakePage()

    summary = execute_action(
        page,
        {"action": "click_button", "button_text": "Join Group Buy"},
    )

    assert summary == "Button 'Join Group Buy' is disabled; click was skipped."
    assert not page.locator.clicked


def test_detect_changed_files_reports_promotable_edits(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    main_path = app_dir / "main.py"
    main_path.write_text("value = 1\n")
    before = snapshot_promotable_files(tmp_path)

    main_path.write_text("value = 2\n")

    assert detect_changed_files(tmp_path, before) == ["app/main.py"]


def test_apply_codex_reported_file_contents_writes_promotable_files(tmp_path) -> None:
    applied = apply_codex_reported_file_contents(
        tmp_path,
        {
            "changed_files": [
                {
                    "path": "app/main.py",
                    "content": "value = 2\n",
                }
            ]
        },
    )

    assert applied == ["app/main.py"]
    assert (tmp_path / "app" / "main.py").read_text() == "value = 2\n"


def test_apply_codex_reported_file_contents_rejects_path_only_changes(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("value = 1\n")

    try:
        apply_codex_reported_file_contents(
            tmp_path,
            {"changed_files": ["app/main.py"]},
        )
    except ValueError as exc:
        assert "path and full content" in str(exc)
    else:
        raise AssertionError("Expected path-only changed_files to be rejected")


def test_apply_codex_reported_file_contents_rejects_placeholder_content(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    main_path = app_dir / "main.py"
    existing = "value = 1\n" * 200
    main_path.write_text(existing)

    try:
        apply_codex_reported_file_contents(
            tmp_path,
            {
                "changed_files": [
                    {
                        "path": "app/main.py",
                        "content": (
                            "from __future__ import annotations\n\n"
                            "# ... keep existing file content unchanged, except replace one line\n"
                        ),
                    }
                ]
            },
        )
    except ValueError as exc:
        assert "placeholder" in str(exc)
    else:
        raise AssertionError("Expected placeholder content to be rejected")
    assert main_path.read_text() == existing


def test_apply_codex_reported_file_contents_rejects_tiny_replacement_for_large_file(tmp_path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    main_path = app_dir / "main.py"
    existing = "value = 1\n" * 200
    main_path.write_text(existing)

    try:
        apply_codex_reported_file_contents(
            tmp_path,
            {
                "changed_files": [
                    {
                        "path": "app/main.py",
                        "content": "value = 2\n",
                    }
                ]
            },
        )
    except ValueError as exc:
        assert "too small" in str(exc)
    else:
        raise AssertionError("Expected tiny replacement content to be rejected")
    assert main_path.read_text() == existing


def test_codex_prompt_includes_repository_context_for_blocked_tools(tmp_path) -> None:
    task = build_task()
    sandbox = tmp_path / "sandbox"
    app_dir = sandbox / "app"
    tests_dir = sandbox / "tests"
    configs_dir = sandbox / "configs"
    app_dir.mkdir(parents=True)
    tests_dir.mkdir()
    configs_dir.mkdir()
    (app_dir / "main.py").write_text("def calculate_cart_total(cart):\n    return 0\n")
    (tests_dir / "test_shop_smoke.py").write_text("def test_total():\n    assert True\n")
    (configs_dir / "run_config.json").write_text("{}\n")

    prompt = build_codex_prompt(
        task,
        sandbox,
        validation_feedback="Attempt 1 failed because changed_files was empty.",
    )

    assert "Repository context JSON" in prompt
    assert "app/main.py" in prompt
    assert "def calculate_cart_total" in prompt
    assert "Attempt 1 failed" in prompt
    assert "Act as a patch proposer" in prompt
    assert '"changed_files":["relative/path.py"]' not in prompt


def test_codex_exec_command_uses_supported_noninteractive_flags(tmp_path) -> None:
    command = build_codex_command(
        codex_executable="codex.exe",
        sandbox_path=tmp_path,
        model=ModelConfigV1(model_name="gpt-5.3-codex", reasoning_effort="high"),
        last_message_path=tmp_path / "last.json",
    )

    assert command[:2] == ["codex.exe", "exec"]
    assert "--json" in command
    assert "--skip-git-repo-check" in command
    assert "--ignore-rules" in command
    assert 'preferred_auth_method="apikey"' in command
    assert 'approval_policy="never"' in command
    assert 'sandbox_mode="workspace-write"' in command
    assert "-a" not in command
    assert "--color" in command
    assert command[-1] == "-"


def test_codex_model_attempts_use_configured_model_only() -> None:
    attempts = codex_model_attempts(
        ModelConfigV1(model_name="gpt-5.3-codex", reasoning_effort="high")
    )

    assert [attempt.model_name for attempt in attempts] == ["gpt-5.3-codex"]
    assert [attempt.reasoning_effort for attempt in attempts] == ["high"]


def test_get_openai_api_key_accepts_openaikey_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAIKEY", "sk-test")

    assert get_openai_api_key() == ("sk-test", "OPENAIKEY")


def test_ensure_openai_api_key_env_bridges_openaikey_for_raw_client(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAIKEY", "sk-test")

    assert ensure_openai_api_key_env() == "OPENAIKEY"
    assert get_openai_api_key() == ("sk-test", "OPENAI_API_KEY")


def test_raw_gpt_fallback_uses_requested_model_and_high_reasoning() -> None:
    assert RAW_GPT_FIXER_MODEL == "gpt-5.5"
    assert RAW_GPT_FIXER_REASONING_EFFORT == "high"


def test_model_patch_paths_have_sixty_second_timeouts() -> None:
    assert CODEX_EXEC_TIMEOUT_SECONDS == 60
    assert RAW_GPT_FIXER_TIMEOUT_SECONDS == 60


def test_raw_gpt_fallback_triggers_when_codex_tools_are_blocked() -> None:
    assert should_run_raw_gpt_fallback(
        [],
        "patch rejected: writing is blocked by read-only sandbox",
    )
    assert not should_run_raw_gpt_fallback(
        ["app/main.py"],
        "patch rejected: writing is blocked by read-only sandbox",
        target_file="app/main.py",
    )
    assert should_run_raw_gpt_fallback([], "Codex made no changes.")


def test_raw_gpt_fallback_triggers_when_codex_rejected_target_content() -> None:
    assert should_run_raw_gpt_fallback(
        ["tests/test_shop_smoke.py"],
        "Codex reported invalid full replacement content: app/main.py replacement content looks like a placeholder",
        target_file="app/main.py",
    )
    assert not should_run_raw_gpt_fallback(
        ["app/main.py"],
        "Codex reported invalid full replacement content: app/main.py replacement content looks like a placeholder",
        target_file="app/main.py",
    )


def test_raw_gpt_patch_prompt_requires_full_replacement_content(tmp_path) -> None:
    task = build_task()
    sandbox = tmp_path / "sandbox"
    app_dir = sandbox / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").write_text("def calculate_cart_total(cart):\n    return 0\n")

    prompt = build_raw_gpt_patch_prompt(
        task,
        sandbox,
        validation_feedback="Tests failed after Codex returned no changes.",
        codex_summary="writing is blocked by read-only sandbox",
    )

    assert '"changed_files":[{"path":"relative/path.py","content":"full file content"}]' in prompt
    assert "app/main.py" in prompt
    assert "read-only sandbox" in prompt


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
