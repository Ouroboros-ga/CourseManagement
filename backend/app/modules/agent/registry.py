from dataclasses import dataclass

from app.modules.agent.schemas import (
    ImportReviewQuery,
    ObjectionMaterialQuery,
    ObjectionSaveQuery,
    ProbeQuery,
    ReadTaskSubmitQuery,
    ReportExportQuery,
    ResponsibilityQuery,
    SelfAttendanceQuery,
    SummaryQuery,
    TaskStatusQuery,
    TimetableQuery,
    ToolArguments,
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[ToolArguments]
    entry_kinds: frozenset[str]
    version: str = "v1"
    workflow_kind: str | None = None


class ToolRegistry:
    """Only implemented tools are discoverable; this is not a permission matrix."""

    def __init__(self):
        specs = (
            ToolSpec(
                "read_task_submit",
                "Queue a supported read task for this run and return a fixed human UI handoff",
                ReadTaskSubmitQuery,
                frozenset({"MANAGEMENT"}),
            ),
            ToolSpec(
                "import_preview_review",
                "Review owned import previews; human conflict review and saving remain required",
                ImportReviewQuery,
                frozenset({"MANAGEMENT"}),
            ),
            ToolSpec(
                "objection_case_get",
                "Read the bound objection and permitted material metadata",
                ProbeQuery,
                frozenset({"AUTOMATION"}),
                workflow_kind="objection",
            ),
            ToolSpec(
                "objection_material_access",
                "Get short-lived access to a bound proof file",
                ObjectionMaterialQuery,
                frozenset({"AUTOMATION"}),
                workflow_kind="objection",
            ),
            ToolSpec(
                "objection_precheck_save",
                "Save advice only; never finalize attendance or objection",
                ObjectionSaveQuery,
                frozenset({"AUTOMATION"}),
                workflow_kind="objection",
            ),
            ToolSpec(
                "change_prepare",
                "Prepare a replacement for the bound change request",
                ProbeQuery,
                frozenset({"AUTOMATION"}),
                workflow_kind="change",
            ),
            ToolSpec(
                "change_apply",
                "Apply the validated replacement for the bound request",
                ProbeQuery,
                frozenset({"AUTOMATION"}),
                workflow_kind="change",
            ),
            ToolSpec(
                "task_status_get",
                "Read a task created in this run",
                TaskStatusQuery,
                frozenset({"MANAGEMENT", "SELF_SERVICE"}),
            ),
            ToolSpec(
                "system_probe",
                "Check tool protocol, without personal data",
                ProbeQuery,
                frozenset({"MANAGEMENT", "SELF_SERVICE"}),
            ),
            ToolSpec(
                "report_attendance_summary",
                "Read attendance totals in the current scope",
                SummaryQuery,
                frozenset({"MANAGEMENT"}),
            ),
            ToolSpec(
                "report_attendance_export_prepare",
                "Prepare an authenticated download action; the file is generated only on download",
                ReportExportQuery,
                frozenset({"MANAGEMENT"}),
            ),
            ToolSpec(
                "self_attendance_list",
                "Read the signed-in student's attendance",
                SelfAttendanceQuery,
                frozenset({"SELF_SERVICE"}),
            ),
            ToolSpec(
                "self_timetable_get",
                "Read the signed-in student's saved timetable",
                TimetableQuery,
                frozenset({"SELF_SERVICE"}),
            ),
            ToolSpec(
                "responsibility_tasks_list",
                "Read tasks in the current responsibility area",
                ResponsibilityQuery,
                frozenset({"MANAGEMENT"}),
            ),
        )
        self._tools = {spec.name: spec for spec in specs}
        if len(self._tools) != len(specs):
            raise ValueError("Duplicate tool name")

    def get(self, name: str) -> ToolSpec:
        return self._tools[name]

    def list_for(self, entry_kind: str, workflow_kind: str | None = None) -> tuple[ToolSpec, ...]:
        return tuple(
            spec
            for spec in self._tools.values()
            if entry_kind in spec.entry_kinds and spec.workflow_kind == workflow_kind
        )
