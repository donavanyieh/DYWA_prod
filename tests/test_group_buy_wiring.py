from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import agents.personas.run as persona_run
from app.buggy_main_seed import app as seed_app
from app.main import app
from scripts.reset_stage0 import reset_stage0
from shared.contracts.models import (
    ArtifactRefV1,
    BugEnvironmentV1,
    BugEvidenceV1,
    BugReportV1,
    ModelConfigV1,
    PersonaConfigV1,
    RunConfigV1,
    TranscriptEventV1,
)
from shared.contracts.validate import validate_file
from shared.io import read_json


GROUP_BUY_PERSONA_IDS = [
    "persona_gb_flow",
    "persona_gb_price",
    "persona_gb_contract",
    "persona_gb_security",
    "persona_gb_data_integrity",
]


def sample_bug_report() -> BugReportV1:
    return BugReportV1(
        report_id="bugrep_group_buy_test",
        run_id="run_memory_test",
        persona_id="persona_gb_flow",
        created_at="2026-06-06T12:00:00Z",
        title="Group-buy confirmation lost the return button",
        severity_guess="medium",
        confidence=0.8,
        observed_behavior="The confirmation page did not show a Group Buy button.",
        expected_behavior="Confirmation should include a Group Buy button.",
        reproduction_steps=[
            "Click Group Buy.",
            "Click Place Order.",
            "Inspect the confirmation page.",
        ],
        evidence=BugEvidenceV1(transcript_event_ids=[], artifacts=[]),
        environment=BugEnvironmentV1(
            app_base_url="http://127.0.0.1:8765",
            browser="chromium",
            viewport="1440x900",
        ),
        metadata={},
    )


def test_group_buy_contract_fixtures_validate() -> None:
    assert validate_file(Path("fixtures/contracts/bug_report.group_buy.valid.json")) == "BugReportV1"
    assert (
        validate_file(Path("fixtures/contracts/transcript_event.group_buy.valid.json"))
        == "TranscriptEventV1"
    )


def test_run_config_personas_are_exactly_group_buy_templates() -> None:
    config = RunConfigV1.model_validate(read_json(Path("configs/run_config.json")))

    assert [persona.persona_id for persona in config.personas] == GROUP_BUY_PERSONA_IDS
    assert all(persona.model.model_name == "gpt-5" for persona in config.personas)


def test_orchestrator_uses_configured_personas_without_hardcoded_ids() -> None:
    source = Path("orchestrator/run.py").read_text()

    assert "for template in config.personas" in source
    assert not any(persona_id in source for persona_id in GROUP_BUY_PERSONA_IDS)
    assert "persona_general_shopper" not in source


def test_stage0_seed_placeholder_survives_reset_to_temp_target(tmp_path: Path) -> None:
    seed_text = Path("app/buggy_main_seed.py").read_text()
    assert "/group-buy/checkout" in seed_text
    assert "/group-buy/place-order" in seed_text
    assert "@app.get(\"/group-buy\"" in seed_text
    assert "Group Buy" in seed_text

    config_data = read_json(Path("configs/run_config.json"))
    target = tmp_path / "main_after_reset.py"
    config_data["stage0"]["restore_files"] = [
        {"source": "app/buggy_main_seed.py", "target": str(target)}
    ]
    config = RunConfigV1.model_validate(config_data)

    result = reset_stage0("run_stage0_test", config)
    reset_text = target.read_text()

    assert result.status == "completed"
    assert str(target) in result.restored_files
    assert "/group-buy/checkout" in reset_text
    assert "/group-buy/place-order" in reset_text
    assert "@app.get(\"/group-buy\"" in reset_text
    assert "Group Buy" in reset_text


def test_seed_placeholder_group_buy_flow() -> None:
    client = TestClient(seed_app)

    home = client.get("/")
    assert home.status_code == 200
    assert "Group Buy" in home.text

    checkout = client.get("/group-buy/checkout")
    assert checkout.status_code == 200
    assert "Place Order" in checkout.text

    confirmation = client.post("/group-buy/place-order")
    assert confirmation.status_code == 200
    assert "Order Confirmation" in confirmation.text
    assert "Group Buy" in confirmation.text

    group_buy = client.get("/group-buy")
    assert group_buy.status_code == 200
    assert "Participants: 1" in group_buy.text


def test_current_app_serves_group_buy_and_checkout_surfaces() -> None:
    client = TestClient(app)

    assert client.get("/").status_code == 200
    assert client.get("/api/products").status_code == 200
    checkout = client.get("/checkout")
    assert checkout.status_code == 200
    assert "Checkout" in checkout.text


def test_memory_lifecycle_and_fresh_load(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(persona_run, "MEMORY_DIR", tmp_path)
    report = sample_bug_report()
    signature = persona_run.bug_signature(report)

    memory = persona_run.empty_memory("persona_gb_flow")
    memory = persona_run.reconcile_memory(
        memory,
        run_id="run_memory_1",
        emitted_reports=[report],
    )
    assert memory["run_count"] == 1
    assert memory["known_findings"][0]["signature"] == signature
    assert memory["known_findings"][0]["status"] == "open"

    memory = persona_run.reconcile_memory(
        memory,
        run_id="run_memory_2",
        emitted_reports=[],
    )
    assert memory["run_count"] == 2
    assert memory["known_findings"][0]["status"] == "resolved"

    memory = persona_run.reconcile_memory(
        memory,
        run_id="run_memory_3",
        emitted_reports=[report],
    )
    assert memory["run_count"] == 3
    assert memory["known_findings"][0]["status"] == "regressed"

    persona_run.save_memory(memory)
    assert persona_run.load_memory("persona_gb_flow")["run_count"] == 3
    assert persona_run.load_memory("persona_gb_flow", fresh=True) == persona_run.empty_memory(
        "persona_gb_flow"
    )


def test_memory_summary_is_injected_into_model_instructions(tmp_path: Path) -> None:
    screenshot = tmp_path / "screen_000.png"
    screenshot.write_bytes(b"not-used-by-fake-client")
    captured: dict[str, object] = {}

    class FakeClient:
        def create_json(self, **kwargs):
            captured.update(kwargs)
            return {"action": "finish", "stop_reason": "goal_reached"}

    config = PersonaConfigV1(
        run_id="run_prompt_test",
        persona_id="persona_gb_flow",
        app_base_url="http://127.0.0.1:8765",
        goal="Walk the group-buy placeholder flow.",
        traits={},
        constraints={
            "max_duration_ms": 120000,
            "max_actions": 1,
            "viewport": {"width": 1440, "height": 900},
            "headless": True,
            "slow_mo_ms": 0,
        },
        artifact_dir=str(tmp_path),
        model=ModelConfigV1(),
    )
    memory = persona_run.reconcile_memory(
        persona_run.empty_memory("persona_gb_flow"),
        run_id="run_prompt_prior",
        emitted_reports=[sample_bug_report()],
    )
    artifact = ArtifactRefV1(
        artifact_id="art_prompt_screen",
        type="screenshot",
        uri=str(screenshot),
        mime_type="image/png",
        created_at="2026-06-06T12:00:00Z",
    )

    action = persona_run.ask_for_action(
        client=FakeClient(),
        config=config,
        page_state={"url": "http://127.0.0.1:8765", "text": "Group Buy", "buttons": ["Group Buy"]},
        screenshot=artifact,
        history=[],
        memory=memory,
    )

    assert action["action"] == "finish"
    assert "MEMORY - prior runs" in str(captured["instructions"])
    assert "prior findings as hypotheses" in str(captured["instructions"])
