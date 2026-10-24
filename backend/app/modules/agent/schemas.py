from datetime import date
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.modules.objection.precheck_schemas import PrecheckResult

Id = Annotated[str, StringConstraints(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]
EntryKind = Literal["MANAGEMENT", "SELF_SERVICE", "AUTOMATION"]


class AppConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    app_key_id: str = Field(min_length=1, max_length=64)
    key_digest: str = Field(pattern=r"^[0-9a-f]{64}$", repr=False)
    entry_kind: EntryKind
    environment: str = Field(min_length=1, max_length=32)
    workflow_kind: Literal["change", "objection"] | None = None

    @model_validator(mode="after")
    def valid_workflow(self):
        if (self.entry_kind == "AUTOMATION") != (self.workflow_kind is not None):
            raise ValueError("Automation requires an implemented, policy-bound workflow")
        return self


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def validate_ids(self):
        for name, value in self.__dict__.items():
            if name.endswith("_id") and value is not None and int(value) >= 2**63:
                raise ValueError("ID exceeds supported range")
        return self


class ProbeQuery(ToolArguments):
    pass


class ObjectionMaterialQuery(ToolArguments):
    file_id: Id


class ObjectionSaveQuery(ToolArguments):
    result: PrecheckResult


class TaskStatusQuery(ToolArguments):
    task_id: Id


class SelfAttendanceQuery(ToolArguments):
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=20, ge=1, le=50)
    task_id: Id | None = None
    effective_type: Literal["NORMAL", "LEAVE", "LATE", "ABSENT"] | None = None


class TimetableQuery(ToolArguments):
    semester_id: Id


class SummaryQuery(TimetableQuery):
    week_no: int | None = Field(default=None, ge=1, le=60)
    date_from: date | None = None
    date_to: date | None = None

    @model_validator(mode="after")
    def bounded_window(self):
        ranged = self.date_from is not None or self.date_to is not None
        if (self.week_no is not None) == ranged:
            raise ValueError("Choose week_no or a complete date range")
        if ranged:
            if self.date_from is None or self.date_to is None:
                raise ValueError("Both dates are required")
            if not 0 <= (self.date_to - self.date_from).days <= 92:
                raise ValueError("Date range must be ordered and at most 93 days")
        return self


class ReportExportQuery(SummaryQuery):
    format: Literal["ANALYTICS_XLSX", "DETAIL_DOCX", "STUDY_XLSX"] = "ANALYTICS_XLSX"


class ResponsibilityQuery(TimetableQuery):
    week_no: int = Field(ge=1, le=60)
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=20, ge=1, le=50)


class TaskSubmit(ToolArguments):
    run_id: Id
    tool_name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]+$")
    arguments: dict[str, Any]
    request_key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class ToolResult(BaseModel):
    status: Literal["SUCCEEDED", "QUEUED", "RUNNING", "MANUAL_REQUIRED", "FAILED"]
    data: dict[str, Any] | None = None
    task_id: str | None = None
    result_ref: str | None = None
    error_code: str | None = None
    retryable: bool = False
    trace_id: str
