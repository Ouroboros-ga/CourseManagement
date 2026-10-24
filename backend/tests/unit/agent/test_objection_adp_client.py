import logging

import pytest
from app.core.config import get_settings
from app.modules.agent.adp_client import AdpCallError, AdpWorkflowClient
from app.modules.agent.adp_schemas import ObjectionAdpConfiguration
from tests.unit.agent.test_adp_client import FakeSDK, config


def precheck_config(**changes):
    return ObjectionAdpConfiguration(
        **{
            **config().model_dump(),
            "app_id": "987654321",
            "proof_delivery_verified": True,
            **changes,
        }
    )


def test_precheck_uses_independent_application_fixed_query_and_redacted_sdk_calls(caplog):
    sdk = FakeSDK()
    client = AdpWorkflowClient(
        precheck_config(), workflow_kind="objection", sdk_factory=lambda *_: sdk
    )
    with caplog.at_level(logging.DEBUG):
        created = client.start_objection("t" * 43, caller_ref="run-7")
    assert created.workflow_run_id == "wfr-test-one"
    payload = sdk.creates[0]
    assert payload["AppId"] == "987654321" and "申诉预审" in payload["Query"]
    assert "t" * 43 not in payload["Query"] and "t" * 43 not in caplog.text
    assert payload["CustomVariableList"] == [{"Name": "agent_run_token", "Value": "t" * 43}]


def test_unverified_material_delivery_blocks_before_sdk_and_cross_kind_calls_are_rejected():
    sdk = FakeSDK()
    client = AdpWorkflowClient(
        precheck_config(proof_delivery_verified=False),
        workflow_kind="objection",
        sdk_factory=lambda *_: sdk,
    )
    with pytest.raises(AdpCallError) as rejected:
        client.start_objection("t" * 43, caller_ref="run-7")
    assert rejected.value.code == "PROOF_DELIVERY_UNVERIFIED" and sdk.creates == []
    with pytest.raises(AdpCallError):
        client.start_change("t" * 43, caller_ref="run-7")
    with pytest.raises(AdpCallError):
        AdpWorkflowClient(config(), sdk_factory=lambda *_: sdk).start_objection(
            "t" * 43, caller_ref="run-7"
        )
    assert sdk.creates == []


def test_settings_factory_never_falls_back_to_change_application(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "agent_adp_enabled", True)
    monkeypatch.setattr(settings, "agent_adp_config", config())
    monkeypatch.setattr(settings, "agent_adp_objection_config", None)
    with pytest.raises(AdpCallError) as missing:
        AdpWorkflowClient.from_settings(settings, workflow_kind="objection")
    assert missing.value.code == "ADP_NOT_CONFIGURED"
    monkeypatch.setattr(settings, "agent_adp_objection_config", precheck_config())
    client = AdpWorkflowClient.from_settings(settings, workflow_kind="objection")
    assert client.config.app_id == "987654321" and client.workflow_kind == "objection"
    monkeypatch.setattr(
        settings, "agent_adp_objection_config", precheck_config(app_id=config().app_id)
    )
    with pytest.raises(AdpCallError) as conflicting:
        AdpWorkflowClient.from_settings(settings, workflow_kind="objection")
    assert conflicting.value.code == "WORKFLOW_APPLICATION_CONFLICT"
