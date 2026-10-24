"""ADP 2026-05-20 adapter. Transport acceptance is never a business commit receipt."""

import logging
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Literal

from tencentcloud.adp.v20260520 import adp_client, models
from tencentcloud.common.credential import Credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.retry import NoopRetryer

from app.modules.agent.adp_schemas import AdpConfiguration

_sensitive_call = ContextVar("adp_sensitive_call", default=False)
_identifier = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
AdpStatus = Literal["QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "CANCELED"]


class _SDKPayloadFilter(logging.Filter):
    def filter(self, record):
        # The SDK debug formatter includes raw request/response bodies and API variables.
        return not _sensitive_call.get()


_payload_filter = _SDKPayloadFilter()


class AdpCallError(Exception):
    def __init__(self, code: str, *, ambiguous=False, retryable=False):
        super().__init__(code)
        self.code, self.ambiguous, self.retryable = code, ambiguous, retryable


@dataclass(frozen=True)
class AdpCreated:
    workflow_run_id: str
    request_id: str


@dataclass(frozen=True)
class AdpSnapshot:
    workflow_run_id: str
    status: AdpStatus
    request_id: str

    @property
    def terminal(self):
        return self.status not in {"QUEUED", "RUNNING"}


@dataclass(frozen=True)
class AdpWaitResult:
    snapshot: AdpSnapshot | None
    reason: Literal["TERMINAL", "TIME_BUDGET", "POLL_LIMIT"]


def build_sdk(config: AdpConfiguration, timeout: float):
    credential = Credential(
        config.secret_id.get_secret_value(),
        config.secret_key.get_secret_value(),
        config.session_token.get_secret_value() if config.session_token else None,
    )
    profile = ClientProfile(
        httpProfile=HttpProfile(
            protocol="https",
            endpoint="adp.tencentcloudapi.com",
            reqTimeout=min(timeout, config.timeout_seconds),
        ),
        retryer=NoopRetryer(),
    )
    return adp_client.AdpClient(credential, config.region, profile)


def _id(value, *, ambiguous=False):
    if not isinstance(value, str) or _identifier.fullmatch(value) is None:
        raise AdpCallError("UPSTREAM_BAD_RESPONSE", ambiguous=ambiguous)
    return value


class AdpWorkflowClient:
    @classmethod
    def from_settings(cls, settings=None, *, workflow_kind="change"):
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
        config = (
            settings.agent_adp_objection_config
            if workflow_kind == "objection"
            else settings.agent_adp_config
        )
        if not settings.agent_adp_enabled or config is None:
            raise AdpCallError("ADP_NOT_CONFIGURED")
        if (
            workflow_kind == "objection"
            and settings.agent_adp_config is not None
            and config.app_id == settings.agent_adp_config.app_id
        ):
            raise AdpCallError("WORKFLOW_APPLICATION_CONFLICT")
        return cls(config, workflow_kind=workflow_kind)

    def __init__(
        self,
        config: AdpConfiguration,
        *,
        workflow_kind: Literal["change", "objection"] = "change",
        sdk_factory=build_sdk,
        clock=time.monotonic,
        sleeper=time.sleep,
    ):
        if workflow_kind not in {"change", "objection"}:
            raise AdpCallError("INVALID_LOCAL_INPUT")
        self.config, self.workflow_kind = config, workflow_kind
        self.sdk_factory, self.clock, self.sleep = sdk_factory, clock, sleeper
        logger = logging.getLogger("tencentcloud_sdk_common")
        if _payload_filter not in logger.filters:
            logger.addFilter(_payload_filter)

    def _call(self, action, request, *, timeout=None):
        marker = _sensitive_call.set(True)
        try:
            sdk = self.sdk_factory(self.config, timeout or self.config.timeout_seconds)
            return getattr(sdk, action)(request)
        except TencentCloudSDKException as error:
            code = error.get_code() or ""
            root = code.split(".", 1)[0]
            explicit_rejection = root in {
                "AuthFailure",
                "UnauthorizedOperation",
                "InvalidParameter",
                "MissingParameter",
                "InvalidParameterValue",
                "LimitExceeded",
                "RequestLimitExceeded",
                "ResourceNotFound",
                "UnsupportedOperation",
            }
            retryable = root in {
                "ClientNetworkError",
                "InternalError",
                "LimitExceeded",
                "RequestLimitExceeded",
                "RequestTimeout",
            }
            raise AdpCallError(
                "UPSTREAM_REJECTED" if explicit_rejection else "UPSTREAM_UNCERTAIN",
                ambiguous=action == "CreateWorkflowRun" and not explicit_rejection,
                retryable=retryable and (action != "CreateWorkflowRun" or explicit_rejection),
            ) from None
        except Exception:
            # Never propagate SDK exception text: it can contain raw credentials/variables.
            raise AdpCallError(
                "UPSTREAM_UNCERTAIN",
                ambiguous=action == "CreateWorkflowRun",
                retryable=action != "CreateWorkflowRun",
            ) from None
        finally:
            _sensitive_call.reset(marker)

    def start_change(self, run_token: str, *, caller_ref: str) -> AdpCreated:
        if self.workflow_kind != "change":
            raise AdpCallError("WORKFLOW_APPLICATION_CONFLICT")
        return self._start(run_token, caller_ref=caller_ref, query="执行已绑定的志愿者换班流程")

    def start_objection(self, run_token: str, *, caller_ref: str) -> AdpCreated:
        if self.workflow_kind != "objection":
            raise AdpCallError("WORKFLOW_APPLICATION_CONFLICT")
        if not getattr(self.config, "proof_delivery_verified", False):
            raise AdpCallError("PROOF_DELIVERY_UNVERIFIED")
        return self._start(
            run_token, caller_ref=caller_ref, query="执行已绑定的考勤申诉预审流程，仅生成预审建议"
        )

    def _start(self, run_token: str, *, caller_ref: str, query: str) -> AdpCreated:
        if not self.config.header_binding_verified:
            raise AdpCallError("HEADER_BINDING_UNVERIFIED")
        if (
            not isinstance(run_token, str)
            or not 32 <= len(run_token) <= 512
            or not isinstance(caller_ref, str)
            or _identifier.fullmatch(caller_ref) is None
            or re.fullmatch(r"[A-Za-z0-9_-]+", run_token) is None
        ):
            raise AdpCallError("INVALID_LOCAL_INPUT")
        request = models.CreateWorkflowRunRequest()
        request.AppId, request.Domain = self.config.app_id, self.config.domain
        request.Query = query
        request.UserId = caller_ref
        variable = models.CustomVariable()
        variable.Name, variable.Value = "agent_run_token", run_token
        request.CustomVariableList = [variable]
        response = self._call("CreateWorkflowRun", request)
        try:
            return AdpCreated(
                _id(response.WorkflowRunId, ambiguous=True), _id(response.RequestId, ambiguous=True)
            )
        except AttributeError:
            raise AdpCallError("UPSTREAM_BAD_RESPONSE", ambiguous=True) from None

    def describe(self, workflow_run_id: str, *, timeout=None) -> AdpSnapshot:
        _id(workflow_run_id)
        request = models.DescribeWorkflowRunRequest()
        request.AppId, request.WorkflowRunId = self.config.app_id, workflow_run_id
        request.IncludeWorkflowGraph = False
        response = self._call("DescribeWorkflowRun", request, timeout=timeout)
        try:
            summary = response.WorkflowRun.WorkflowRunSummary
            profile, result = summary.WorkflowRunProfile, summary.WorkflowRunResult
            status = result.Status
            if (
                profile.AppId != self.config.app_id
                or profile.WorkflowRunId != workflow_run_id
                or summary.Domain != self.config.domain
                or type(status) is not int
                or status not in range(1, 6)
            ):
                raise AdpCallError("UPSTREAM_BAD_RESPONSE")
            states: dict[int, AdpStatus] = {
                1: "QUEUED",
                2: "RUNNING",
                3: "SUCCEEDED",
                4: "FAILED",
                5: "CANCELED",
            }
            return AdpSnapshot(workflow_run_id, states[status], _id(response.RequestId))
        except AttributeError:
            raise AdpCallError("UPSTREAM_BAD_RESPONSE") from None

    def wait(
        self, workflow_run_id: str, *, max_polls=3, budget_seconds=15, interval_seconds=1
    ) -> AdpWaitResult:
        if (
            type(max_polls) is not int
            or not 1 <= max_polls <= 10
            or not 0 < budget_seconds <= 30
            or not 0.1 <= interval_seconds <= 5
        ):
            raise AdpCallError("INVALID_LOCAL_INPUT")
        deadline = self.clock() + budget_seconds
        latest = None
        for index in range(max_polls):
            remaining = deadline - self.clock()
            if remaining <= 0:
                return AdpWaitResult(latest, "TIME_BUDGET")
            latest = self.describe(
                workflow_run_id, timeout=min(remaining, self.config.timeout_seconds)
            )
            if latest.terminal:
                return AdpWaitResult(latest, "TERMINAL")
            remaining = deadline - self.clock()
            if remaining <= 0:
                return AdpWaitResult(latest, "TIME_BUDGET")
            if index + 1 < max_polls:
                self.sleep(min(interval_seconds, remaining))
        return AdpWaitResult(latest, "POLL_LIMIT")
