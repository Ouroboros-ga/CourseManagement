from app.modules.agent.contract_export import build_contract


def test_export_is_small_and_never_exposes_identity_parameters():
    contract = build_contract()
    assert contract["openapi"] == "3.0.3"
    assert len(contract["paths"]) == 9
    assert "/api/v1/academic/students" not in contract["paths"]
    operation = contract["paths"]["/api/v1/agent-tools/v1/calls/self_attendance_list"]["post"]
    inputs = operation["requestBody"]["content"]["application/json"]["schema"]
    assert inputs["properties"]["arguments"]["additionalProperties"] is False
    assert "student_id" not in inputs["properties"]["arguments"]["properties"]
    assert operation["security"] == [{"ToolAppKey": [], "AgentRunToken": []}]


def test_nullable_query_fields_are_openapi_30_compatible():
    contract = build_contract()
    operation = contract["paths"]["/api/v1/agent-tools/v1/calls/self_attendance_list"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    task_id = schema["properties"]["arguments"]["properties"]["task_id"]
    assert task_id["type"] == "string"
    assert task_id["nullable"] is True


def test_task_submission_contract_contains_only_the_two_supported_read_tasks():
    import json

    operation = build_contract()["paths"]["/api/v1/agent-tools/v1/calls/read_task_submit"]["post"]
    schema = operation["requestBody"]["content"]["application/json"]["schema"]["properties"][
        "arguments"
    ]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]["tool_name"]["enum"]) == {
        "report_attendance_export_prepare",
        "import_preview_review",
    }
    assert all(
        branch["additionalProperties"] is False
        for branch in schema["properties"]["arguments"]["anyOf"]
    )
    assert "$ref" not in json.dumps(schema)


def test_background_contract_contains_only_bound_empty_argument_tools():
    contract = build_contract(automation=True)
    assert {path.rsplit("/", 1)[-1] for path in contract["paths"]} == {
        "change_prepare",
        "change_apply",
    }
    for path in contract["paths"].values():
        schema = path["post"]["requestBody"]["content"]["application/json"]["schema"]
        assert schema["properties"]["arguments"]["properties"] == {}
        assert schema["properties"]["arguments"]["additionalProperties"] is False
