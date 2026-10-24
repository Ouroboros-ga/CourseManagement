"""Offline export for ADP; no server credentials or database access."""

import json
from typing import Any

from app.modules.agent.registry import ToolRegistry
from app.modules.agent.schemas import ToolResult


def openapi_schema(value: Any, definitions: dict | None = None) -> Any:
    if isinstance(value, list):
        return [openapi_schema(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    definitions = value.get("$defs", definitions or {})
    if "$ref" in value:
        reference = value["$ref"]
        if not reference.startswith("#/$defs/") or reference[8:] not in definitions:
            raise ValueError("Tool schema contains an unresolved reference")
        return openapi_schema(
            {**definitions[reference[8:]], **{k: v for k, v in value.items() if k != "$ref"}},
            definitions,
        )
    result = {
        key: openapi_schema(item, definitions) for key, item in value.items() if key != "$defs"
    }
    alternatives = result.get("anyOf", [])
    if len(alternatives) == 2 and {"type": "null"} in alternatives:
        result.pop("anyOf")
        result.update(next(item for item in alternatives if item != {"type": "null"}))
        result["nullable"] = True
    return result


def build_contract(*, automation: bool = False, workflow_kind: str | None = None) -> dict:
    if workflow_kind not in (None, "change", "objection") or (
        automation and workflow_kind not in (None, "change")
    ):
        raise ValueError("Select exactly one implemented workflow")
    workflow_kind = workflow_kind or ("change" if automation else None)
    paths = {}
    registry = ToolRegistry()
    names = (
        {spec.name for spec in registry.list_for("AUTOMATION", workflow_kind)}
        if workflow_kind is not None
        else {
            spec.name for kind in ("MANAGEMENT", "SELF_SERVICE") for spec in registry.list_for(kind)
        }
    )
    for name in sorted(names):
        spec = registry.get(name)
        paths[f"/api/v1/agent-tools/v1/calls/{name}"] = {
            "post": {
                "operationId": name,
                "summary": spec.description,
                "security": [{"ToolAppKey": [], "AgentRunToken": []}],
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["arguments"],
                                "properties": {
                                    "arguments": openapi_schema(
                                        spec.input_model.model_json_schema()
                                    )
                                },
                            }
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Result wrapped in data/requestId",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["data", "requestId"],
                                    "properties": {
                                        "data": openapi_schema(ToolResult.model_json_schema()),
                                        "requestId": {"type": "string", "nullable": True},
                                    },
                                }
                            }
                        },
                    },
                    "401": {"description": "Invalid application credentials"},
                    "403": {"description": "Run expired or action forbidden"},
                    "404": {"description": "Tool or resource unavailable"},
                    "409": {"description": "Source, execution attempt or business state changed"},
                    "422": {"description": "Invalid parameters or result too large"},
                },
            }
        }
    return {
        "openapi": "3.0.3",
        "info": {
            "title": (
                f"Course {workflow_kind.title()} Workflow Tools"
                if workflow_kind
                else "Course Agent Tools"
            ),
            "version": "v1",
        },
        "paths": paths,
        "components": {
            "securitySchemes": {
                "ToolAppKey": {"type": "apiKey", "in": "header", "name": "X-Tool-App-Key"},
                "AgentRunToken": {"type": "apiKey", "in": "header", "name": "X-Agent-Run-Token"},
            }
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    workflow = parser.add_mutually_exclusive_group()
    workflow.add_argument("--automation-change", action="store_true")
    workflow.add_argument("--automation-objection", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            build_contract(
                automation=args.automation_change,
                workflow_kind="objection" if args.automation_objection else None,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
