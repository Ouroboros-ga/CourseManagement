import json
import logging

import pytest
from app.modules.agent.adp_client import AdpCallError, AdpWorkflowClient, build_sdk
from app.modules.agent.adp_schemas import AdpConfiguration
from tencentcloud.adp.v20260520 import models
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException


def config(**changes):
    return AdpConfiguration(
        app_id="123456789",
        region="ap-guangzhou",
        domain=1,
        secret_id="synthetic-secret-id",
        secret_key="synthetic-secret-key",
        header_binding_verified=True,
        **changes,
    )


def created():
    value = models.CreateWorkflowRunResponse()
    value.from_json_string(json.dumps({"WorkflowRunId": "wfr-test-one", "RequestId": "req-1"}))
    return value


def described(status, *, app_id="123456789", run_id="wfr-test-one", **extra):
    value = models.DescribeWorkflowRunResponse()
    value.from_json_string(
        json.dumps(
            {
                "WorkflowRun": {
                    "WorkflowRunSummary": {
                        "Domain": 1,
                        "WorkflowRunProfile": {"AppId": app_id, "WorkflowRunId": run_id},
                        "WorkflowRunResult": {"Status": status},
                    },
                    **extra,
                },
                "RequestId": "req-2",
            }
        )
    )
    return value


class FakeSDK:
    def __init__(self):
        self.creates = []
        self.describes = []
        self.statuses = [2]
        self.failure = None

    def CreateWorkflowRun(self, request):
        self.creates.append(json.loads(request.to_json_string()))
        logging.getLogger("tencentcloud_sdk_common").debug("Raw request: %s", self.creates[-1])
        if self.failure:
            raise self.failure
        return created()

    def DescribeWorkflowRun(self, request):
        self.describes.append(json.loads(request.to_json_string()))
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        return described(status)


def client(sdk=None, **kwargs):
    sdk = sdk or FakeSDK()
    return AdpWorkflowClient(config(), sdk_factory=lambda *_: sdk, **kwargs), sdk


def test_create_uses_new_sdk_parameters_and_no_prompt_credentials(caplog):
    agent, sdk = client()
    with caplog.at_level(logging.DEBUG):
        result = agent.start_change("r" * 43, caller_ref="run-13")
    assert result.workflow_run_id == "wfr-test-one"
    assert len(sdk.creates) == 1
    payload = sdk.creates[0]
    assert payload["AppId"] == "123456789" and payload["Domain"] == 1
    assert payload["CustomVariableList"] == [{"Name": "agent_run_token", "Value": "r" * 43}]
    assert payload["UserId"] == "run-13"
    assert "r" * 43 not in payload["Query"]
    assert "r" * 43 not in caplog.text
    assert "synthetic-secret-key" not in repr(config())


def test_unverified_header_binding_fails_before_any_outbound_call():
    calls = []
    agent = AdpWorkflowClient(
        config().model_copy(update={"header_binding_verified": False}),
        sdk_factory=lambda *_: calls.append(1),
    )
    with pytest.raises(AdpCallError) as error:
        agent.start_change("r" * 43, caller_ref="run-13")
    assert error.value.code == "HEADER_BINDING_UNVERIFIED"
    assert calls == []


def test_default_sdk_uses_tls_fixed_endpoint_and_no_automatic_retry():
    from tencentcloud.common.retry import NoopRetryer

    sdk = build_sdk(config(), 2.5)
    assert sdk._apiVersion == "2026-05-20"
    assert sdk.profile.httpProfile.endpoint == "adp.tencentcloudapi.com"
    assert sdk.profile.httpProfile.protocol == "https"
    assert sdk.profile.httpProfile.reqTimeout == 2.5
    assert isinstance(sdk.profile.retryer, NoopRetryer)


@pytest.mark.parametrize(
    "remote,local",
    [(1, "QUEUED"), (2, "RUNNING"), (3, "SUCCEEDED"), (4, "FAILED"), (5, "CANCELED")],
)
def test_describe_parses_new_nested_status_and_does_not_return_metadata(remote, local):
    agent, sdk = client()
    sdk.statuses = [remote]
    result = agent.describe("wfr-test-one")
    assert result.status == local
    assert sdk.describes[0]["IncludeWorkflowGraph"] is False
    assert sdk.describes[0]["AppId"] == "123456789"
    assert not hasattr(result, "metadata")


@pytest.mark.parametrize("status", [0, 6, None, True, "3"])
def test_unknown_or_old_workflow_states_are_not_treated_as_success(status):
    agent, sdk = client()
    sdk.statuses = [status]
    with pytest.raises(AdpCallError, match="UPSTREAM_BAD_RESPONSE"):
        agent.describe("wfr-test-one")


@pytest.mark.parametrize(
    "code,ambiguous,retryable",
    [
        ("ClientNetworkError", True, False),
        ("InternalError", True, False),
        ("LimitExceeded", False, True),
        ("AuthFailure.SignatureFailure", False, False),
    ],
)
def test_create_errors_are_sanitized_and_never_retried(code, ambiguous, retryable):
    agent, sdk = client()
    sdk.failure = TencentCloudSDKException(code, "credential=" + "r" * 43)
    with pytest.raises(AdpCallError) as error:
        agent.start_change("r" * 43, caller_ref="run-13")
    assert error.value.ambiguous is ambiguous
    assert error.value.retryable is retryable
    assert "r" * 43 not in str(error.value)
    assert len(sdk.creates) == 1


def test_wait_is_bounded_and_does_not_start_or_cancel_cloud_runs():
    now = [0.0]

    def sleep(seconds):
        now[0] += seconds

    agent, sdk = client(clock=lambda: now[0], sleeper=sleep)
    sdk.statuses = [1, 2, 3]
    result = agent.wait("wfr-test-one", max_polls=2, budget_seconds=10, interval_seconds=1)
    assert result.reason == "POLL_LIMIT" and result.snapshot.status == "RUNNING"
    assert len(sdk.describes) == 2 and sdk.creates == []
    result = agent.wait("wfr-test-one", max_polls=2, budget_seconds=10, interval_seconds=1)
    assert result.reason == "TERMINAL" and result.snapshot.status == "SUCCEEDED"


def test_wait_budget_limits_subsequent_polls_and_per_call_timeout():
    now, timeouts = [0.0], []
    sdk = FakeSDK()

    def factory(_config, timeout):
        timeouts.append(timeout)
        now[0] += 3
        return sdk

    agent = AdpWorkflowClient(
        config(), sdk_factory=factory, clock=lambda: now[0], sleeper=lambda seconds: None
    )
    result = agent.wait("wfr-test-one", max_polls=5, budget_seconds=2, interval_seconds=1)
    assert result.reason == "TIME_BUDGET" and len(timeouts) == 1
    assert timeouts[0] <= 2


def test_missing_create_receipt_is_uncertain_instead_of_safe_to_repeat():
    agent, sdk = client()
    sdk.CreateWorkflowRun = lambda request: models.CreateWorkflowRunResponse()
    with pytest.raises(AdpCallError) as error:
        agent.start_change("r" * 43, caller_ref="run-13")
    assert error.value.ambiguous is True


def test_describe_checks_cloud_app_and_run_identity_and_drops_secret_metadata():
    agent, sdk = client()
    for override in [{"app_id": "9876"}, {"run_id": "wfr-wrong"}]:
        sdk.DescribeWorkflowRun = lambda request, selected=override: described(3, **selected)
        with pytest.raises(AdpCallError):
            agent.describe("wfr-test-one")
    sdk.DescribeWorkflowRun = lambda request: described(
        3,
        WorkflowRunMetadata={
            "CustomVariableList": [{"Name": "agent_run_token", "Value": "r" * 43}],
            "WorkflowGraph": "r" * 43,
        },
    )
    assert "r" * 43 not in repr(agent.describe("wfr-test-one"))


def test_runtime_factory_is_disabled_by_default_and_never_prints_secrets():
    from types import SimpleNamespace

    settings = SimpleNamespace(agent_adp_enabled=False, agent_adp_config=config())
    with pytest.raises(AdpCallError, match="ADP_NOT_CONFIGURED"):
        AdpWorkflowClient.from_settings(settings)
    settings.agent_adp_enabled = True
    assert AdpWorkflowClient.from_settings(settings).config.app_id == "123456789"


def test_uncertain_create_is_never_advertised_as_safe_for_automatic_retry():
    agent, sdk = client()
    sdk.failure = TencentCloudSDKException("ClientNetworkError", "timeout")
    with pytest.raises(AdpCallError) as error:
        agent.start_change("r" * 43, caller_ref="run-13")
    assert error.value.ambiguous is True
    assert error.value.retryable is False


def test_network_error_on_read_only_describe_can_be_retried_later():
    agent, sdk = client()

    def fail(request):
        raise TencentCloudSDKException("ClientNetworkError", "timeout")

    sdk.DescribeWorkflowRun = fail
    with pytest.raises(AdpCallError) as error:
        agent.describe("wfr-test-one")
    assert error.value.ambiguous is False
    assert error.value.retryable is True
