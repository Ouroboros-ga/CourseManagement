from __future__ import annotations

from collections import Counter
from typing import Any

import pytest


@pytest.fixture(scope="module")
def openapi_schema() -> dict[str, Any]:
    # Import the assembled application and inspect its generated document only.
    from app.main import app

    return app.openapi()


def _operations(path_item: dict[str, Any]):
    for method, operation in path_item.items():
        if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head", "trace"}:
            yield method.upper(), operation


def _parameter(parameter: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    reference = parameter.get("$ref")
    if not reference:
        return parameter
    assert reference.startswith("#/components/parameters/"), reference
    name = reference.rsplit("/", 1)[-1]
    return schema["components"]["parameters"][name]


def test_every_college_path_declares_a_valid_required_cid(openapi_schema: dict[str, Any]) -> None:
    paths = openapi_schema["paths"]
    college_paths = {path: item for path, item in paths.items() if "{cid}" in path}
    assert college_paths, "the generated document contains no college-scoped paths"

    for path, path_item in college_paths.items():
        path_parameters = path_item.get("parameters", [])
        for method, operation in _operations(path_item):
            parameters = path_parameters + operation.get("parameters", [])
            cid_parameters = [
                _parameter(parameter, openapi_schema)
                for parameter in parameters
                if _parameter(parameter, openapi_schema).get("name") == "cid"
                and _parameter(parameter, openapi_schema).get("in") == "path"
            ]
            assert len(cid_parameters) == 1, f"{method} {path} must define one path cid"
            parameter = cid_parameters[0]
            assert parameter.get("required") is True, f"{method} {path} cid must be required"
            value_schema = parameter.get("schema", {})
            assert value_schema.get("type") == "integer", f"{method} {path} cid must be an integer"
            assert (
                value_schema.get("exclusiveMinimum") == 0 or value_schema.get("minimum", 0) >= 1
            ), f"{method} {path} cid must be positive"
            assert value_schema.get("maximum") == 2**63 - 1, (
                f"{method} {path} cid must have the BIGINT upper bound"
            )


@pytest.mark.parametrize(
    ("alias_family", "path_match"),
    [
        ("college import", lambda path: "/imports" in path or "/import-templates/" in path),
        ("college inspection", lambda path: "/inspection" in path),
        ("college statistics", lambda path: "/statistics/" in path),
        ("college audit", lambda path: "/audit-logs" in path),
    ],
)
def test_reused_college_alias_families_are_in_the_openapi_contract(
    openapi_schema: dict[str, Any], alias_family: str, path_match
) -> None:
    matching = [path for path in openapi_schema["paths"] if "{cid}" in path and path_match(path)]
    assert matching, f"no {alias_family} alias is present in the generated OpenAPI document"


def test_all_http_operation_ids_are_present_and_unique(openapi_schema: dict[str, Any]) -> None:
    operation_ids = [
        operation.get("operationId")
        for path_item in openapi_schema["paths"].values()
        for _method, operation in _operations(path_item)
    ]
    assert all(operation_ids), "every HTTP operation must have an operation_id"
    duplicates = [
        operation_id for operation_id, count in Counter(operation_ids).items() if count > 1
    ]
    assert not duplicates, f"operation_id values must be unique: {duplicates}"


def test_published_academic_lifecycle_prefix_is_preserved(openapi_schema):
    for suffix in (
        "/enrollment-handoff/tasks",
        "/student-data/preview-file",
        "/teacher-colleges/{user_id}",
    ):
        assert f"/api/v1/academic{suffix}" in openapi_schema["paths"]
