"""个人扩展字段不能冒充正式来源或覆盖服务端条目标识。"""

import pytest
from app.modules.timetable.schemas import EntryCreate, EntryUpdate
from pydantic import ValidationError


@pytest.mark.parametrize("field", [
    "id", "source_schedule_id", "teaching_class_id", "college_id", "class_name", "exceptions",
])
def test_personal_patch_rejects_server_owned_fields(field):
    with pytest.raises(ValidationError):
        EntryUpdate.model_validate({"current_version": 1, field: "forged"})


def test_personal_create_rejects_server_owned_fields():
    with pytest.raises(ValidationError):
        EntryCreate.model_validate({
            "current_version": 1, "course_name": "选修", "weekday": 1, "week_nos": [1],
            "start_time": "08:00", "end_time": "09:00", "college_id": "999",
        })


def test_personal_extra_fields_remain_supported():
    value = EntryUpdate.model_validate({"current_version": 1, "custom_tag": "复习"})
    assert value.model_dump()["custom_tag"] == "复习"


def test_miniapp_snapshot_routes_are_mounted():
    from app.main import create_app

    paths = create_app().openapi()["paths"]
    assert "get" in paths["/api/v1/me/class-timetable"]
    assert "get" in paths["/api/v1/me/timetable-backup"]
    assert "put" in paths["/api/v1/me/timetable-backup"]


def test_miniapp_routes_do_not_require_client_college_context():
    from app.main import create_app

    document = create_app().openapi()
    paths = document["paths"]
    for path, operations in paths.items():
        if not (path.startswith("/api/v1/me/") or path in {
            "/api/v1/me", "/api/v1/auth/wechat/login",
            "/api/v1/inspection-tasks/{task_id}/submissions",
            "/api/v1/inspection-tasks/{task_id}/students",
            "/api/v1/assignment-change-requests",
            "/api/v1/attendance/{record_id}/objections",
        }):
            continue
        for operation in operations.values():
            for parameter in operation.get("parameters", []):
                assert not (parameter["name"] in {"college_id", "cid"}
                            and parameter.get("required")), path
            schema = operation.get("requestBody", {}).get("content", {}).get(
                "application/json", {}).get("schema", {})
            if "$ref" in schema:
                schema = document["components"]["schemas"][
                    schema["$ref"].rsplit("/", 1)[1]]
            assert "college_id" not in schema.get("required", []), path
