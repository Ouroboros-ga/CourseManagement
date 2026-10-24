import pytest
from app.modules.agent.registry import ToolRegistry
from app.modules.agent.schemas import SelfAttendanceQuery, SummaryQuery
from pydantic import ValidationError


@pytest.mark.parametrize("field", ["actor_user_id", "student_id", "college_id", "role"])
def test_self_query_rejects_identity_override(field):
    with pytest.raises(ValidationError) as error:
        SelfAttendanceQuery.model_validate({field: "99"})
    assert error.value.errors()[0]["type"] == "extra_forbidden"


def test_self_directory_never_contains_management_tools():
    names = {tool.name for tool in ToolRegistry().list_for("SELF_SERVICE")}
    assert {"self_attendance_list", "self_timetable_get"} <= names
    assert "report_attendance_summary" not in names
    assert "objection_final_review" not in names


def test_automation_only_exposes_implemented_policy_bound_change_tools():
    assert {tool.name for tool in ToolRegistry().list_for("AUTOMATION", "change")} == {
        "change_prepare", "change_apply"
    }
    assert ToolRegistry().list_for("AUTOMATION") == ()


def test_unknown_tool_is_not_registered():
    with pytest.raises(KeyError):
        ToolRegistry().get("execute_sql")


@pytest.mark.parametrize("value", [1, "0", "-1", "1e3", "1.0", "01", str(2**63)])
def test_tool_ids_are_canonical_bigint_strings(value):
    with pytest.raises(ValidationError):
        SummaryQuery(semester_id=value, week_no=1)


def test_summary_requires_exactly_one_bounded_window():
    with pytest.raises(ValidationError):
        SummaryQuery(semester_id="1")
    with pytest.raises(ValidationError):
        SummaryQuery(semester_id="1", week_no=1, date_from="2026-10-01")
