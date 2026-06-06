from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SCHEMA_VERSION = "1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactType(StrEnum):
    SCREENSHOT = "screenshot"
    DOM_SNAPSHOT = "dom_snapshot"
    CONSOLE_LOG = "console_log"
    NETWORK_LOG = "network_log"
    PATCH = "patch"
    TEST_REPORT = "test_report"
    TRACE = "trace"
    VIDEO = "video"
    TEXT_LOG = "text_log"


class EventSource(StrEnum):
    SHOPPING_APP = "shopping_app"
    PERSONA_AGENT = "persona_agent"
    VERIFIER = "verifier"
    FIXING_AGENT = "fixing_agent"
    ORCHESTRATOR = "orchestrator"
    DASHBOARD = "dashboard"


class EventStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class VerifierClassification(StrEnum):
    CONFIRMED = "confirmed"
    DUPLICATE = "duplicate"
    INVALID = "invalid"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


class VerifierNextAction(StrEnum):
    SEND_TO_FIXING_AGENT = "send_to_fixing_agent"
    IGNORE = "ignore"
    REQUEST_MORE_EVIDENCE = "request_more_evidence"
    LINK_TO_EXISTING_BUG = "link_to_existing_bug"


class FixStatus(StrEnum):
    FIXED = "fixed"
    NOT_REPRODUCED = "not_reproduced"
    FAILED = "failed"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class TestStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    STAGE_0_RESET = "stage_0_reset"
    PERSONA_EXPLORATION = "persona_exploration"
    VERIFICATION = "verification"
    FIXING = "fixing"
    INTEGRATION_TEST = "integration_test"
    COMPLETE = "complete"


class ComponentStatus(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class ArtifactRefV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    artifact_id: str
    type: ArtifactType
    uri: str
    mime_type: str
    created_at: str
    sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ErrorV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    code: str
    message: str
    recoverable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class TranscriptEventV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    event_id: str
    run_id: str
    source: EventSource
    source_id: str
    event_type: str
    status: EventStatus
    timestamp: str
    duration_ms: int = Field(ge=0)
    summary: str
    artifacts: list[ArtifactRefV1] = Field(default_factory=list)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: ErrorV1 | None = None


class ViewportV1(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class PersonaConstraintsV1(StrictModel):
    max_duration_ms: int = Field(gt=0)
    max_actions: int = Field(gt=0)
    viewport: ViewportV1
    headless: bool = True
    slow_mo_ms: int = Field(default=0, ge=0)


class ModelConfigV1(StrictModel):
    provider: Literal["openai"] = "openai"
    model_name: str = Field(default="gpt-5", min_length=1)
    mode: Literal["live"] = "live"
    reasoning_effort: Literal["minimal", "low", "medium", "high"] | None = "medium"


class PersonaConfigV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id: str
    persona_id: str
    app_base_url: str
    goal: str
    traits: dict[str, str] = Field(default_factory=dict)
    constraints: PersonaConstraintsV1
    artifact_dir: str
    model: ModelConfigV1


class PersonaTemplateV1(StrictModel):
    persona_id: str
    goal: str
    traits: dict[str, str] = Field(default_factory=dict)
    constraints: PersonaConstraintsV1
    model: ModelConfigV1


class BugEvidenceV1(StrictModel):
    transcript_event_ids: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRefV1] = Field(default_factory=list)


class BugEnvironmentV1(StrictModel):
    app_base_url: str
    browser: str
    viewport: str


class BugReportV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    report_id: str
    run_id: str
    persona_id: str
    created_at: str
    title: str
    severity_guess: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    observed_behavior: str
    expected_behavior: str
    reproduction_steps: list[str]
    evidence: BugEvidenceV1
    environment: BugEnvironmentV1
    metadata: dict[str, Any] = Field(default_factory=dict)


class BugReportRefV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    report_id: str


class VerifierInputV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id: str
    report: BugReportV1 | BugReportRefV1
    related_reports: list[BugReportV1] = Field(default_factory=list)
    known_confirmed_bugs: list[str] = Field(default_factory=list)
    expected_behavior_sources: list[str] = Field(default_factory=list)
    transcript_events: list[TranscriptEventV1 | str] = Field(default_factory=list)
    artifacts: list[ArtifactRefV1 | str] = Field(default_factory=list)


class FixTaskRefV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    task_id: str


class VerifierDecisionV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    decision_id: str
    run_id: str
    report_id: str
    created_at: str
    classification: VerifierClassification
    confidence: float = Field(ge=0.0, le=1.0)
    canonical_bug_id: str | None = None
    duplicate_of: str | None = None
    severity: Severity | None = None
    reasoning_summary: str
    required_next_action: VerifierNextAction
    fix_task: FixTaskRefV1 | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfirmedBehaviorV1(StrictModel):
    observed: str
    expected: str


class RepoTargetV1(StrictModel):
    path: str
    entrypoint: str
    test_command: str


class SandboxV1(StrictModel):
    mode: Literal["copy"]
    path: str


class PromotionPolicyV1(StrictModel):
    target_file: str
    requires_tests_green: bool
    requires_contract_validation: bool


class AppRuntimeV1(StrictModel):
    start_command: list[str]
    base_url: str
    health_url: str | None = None
    cwd: str = "."


class Stage0RestoreFileV1(StrictModel):
    source: str
    target: str


class Stage0ConfigV1(StrictModel):
    restore_files: list[Stage0RestoreFileV1]
    bug_seed: str


class VerifierConfigV1(StrictModel):
    expected_behavior_sources: list[str] = Field(default_factory=list)
    model: ModelConfigV1 = Field(default_factory=ModelConfigV1)


class FixingConfigV1(StrictModel):
    model: ModelConfigV1 = Field(
        default_factory=lambda: ModelConfigV1(
            model_name="gpt-5.3-codex",
            reasoning_effort="high",
        )
    )


class RunConfigV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id_prefix: str = "run"
    app: AppRuntimeV1
    stage0: Stage0ConfigV1
    personas: list[PersonaTemplateV1]
    verifier: VerifierConfigV1
    fixing: FixingConfigV1 = Field(default_factory=FixingConfigV1)
    repo: RepoTargetV1
    sandbox_root: str = ".sandbox"
    max_concurrent_personas: int = Field(default=1, ge=1)
    promotion_policy: PromotionPolicyV1


class FixTaskV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    task_id: str
    run_id: str
    canonical_bug_id: str
    created_at: str
    source_report_ids: list[str]
    title: str
    confirmed_behavior: ConfirmedBehaviorV1
    reproduction_steps: list[str]
    evidence_artifacts: list[str] = Field(default_factory=list)
    repo: RepoTargetV1
    sandbox: SandboxV1
    promotion_policy: PromotionPolicyV1
    metadata: dict[str, Any] = Field(default_factory=dict)


class TestSummaryV1(StrictModel):
    command: str
    status: TestStatus
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    duration_ms: int = Field(ge=0)
    report_artifact_id: str | None = None


class FixResultV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    result_id: str
    task_id: str
    run_id: str
    canonical_bug_id: str
    status: FixStatus
    started_at: str
    completed_at: str
    duration_ms: int = Field(ge=0)
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    artifacts: list[ArtifactRefV1] = Field(default_factory=list)
    tests: TestSummaryV1
    promoted: bool
    error: ErrorV1 | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunSummaryV1(StrictModel):
    reports_total: int = Field(ge=0)
    confirmed_total: int = Field(ge=0)
    fixed_total: int = Field(ge=0)
    invalid_total: int = Field(ge=0)
    duplicate_total: int = Field(ge=0)


class RunStateV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id: str
    status: RunStatus
    started_at: str
    completed_at: str | None = None
    stage: RunStage
    components: dict[str, ComponentStatus]
    summary: RunSummaryV1


class Stage0ResetResultV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_id: str
    reset_id: str
    status: EventStatus
    started_at: str
    completed_at: str
    restored_files: list[str]
    bug_seed: str
    error: ErrorV1 | None = None


class DashboardRunBundleV1(StrictModel):
    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    run_state: RunStateV1
    events: list[TranscriptEventV1] = Field(default_factory=list)
    bug_reports: list[BugReportV1] = Field(default_factory=list)
    verifier_decisions: list[VerifierDecisionV1] = Field(default_factory=list)
    fix_results: list[FixResultV1] = Field(default_factory=list)
    artifacts: list[ArtifactRefV1] = Field(default_factory=list)
