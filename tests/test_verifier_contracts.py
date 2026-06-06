from orchestrator.verifier.run import decision_from_payload
from shared.contracts.models import (
    ArtifactRefV1,
    BugEnvironmentV1,
    BugEvidenceV1,
    BugReportV1,
    Severity,
    VerifierClassification,
    VerifierNextAction,
)


def build_report() -> BugReportV1:
    return BugReportV1(
        report_id="bugrep_test_001",
        run_id="run_test_001",
        persona_id="persona_test",
        created_at="2026-06-06T12:00:00Z",
        title="Cart total does not update",
        severity_guess=Severity.HIGH,
        confidence=0.91,
        observed_behavior="The cart total remains unchanged after quantity changes.",
        expected_behavior="The cart total should reflect quantity times unit price.",
        reproduction_steps=["Add item.", "Change quantity.", "Check total."],
        evidence=BugEvidenceV1(
            transcript_event_ids=[],
            artifacts=[
                ArtifactRefV1(
                    artifact_id="art_test_001",
                    type="screenshot",
                    uri="artifacts/run_test/screen.png",
                    mime_type="image/png",
                    created_at="2026-06-06T12:00:01Z",
                    sha256=None,
                    metadata={},
                )
            ],
        ),
        environment=BugEnvironmentV1(
            app_base_url="http://127.0.0.1:8765",
            browser="chromium",
            viewport="1280x720",
        ),
        metadata={},
    )


def test_decision_from_payload_accepts_string_null_optional_fields() -> None:
    decision = decision_from_payload(
        build_report(),
        {
            "classification": "needs_more_evidence",
            "confidence": 0.58,
            "canonical_bug_id": "null",
            "duplicate_of": "none",
            "severity": "null",
            "reasoning_summary": "Evidence is not conclusive enough to create a fix task.",
            "required_next_action": "request_more_evidence",
        },
    )

    assert decision.classification == VerifierClassification.NEEDS_MORE_EVIDENCE
    assert decision.required_next_action == VerifierNextAction.REQUEST_MORE_EVIDENCE
    assert decision.canonical_bug_id is None
    assert decision.duplicate_of is None
    assert decision.severity is None
