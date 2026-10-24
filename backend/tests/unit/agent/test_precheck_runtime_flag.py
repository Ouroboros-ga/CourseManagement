import pytest
from app.core.config import get_settings
from app.modules.identity.router import campus_runtime


@pytest.mark.parametrize("enabled", [False, True])
def test_runtime_reports_precheck_feature_without_connection_details(monkeypatch, enabled):
    monkeypatch.setattr(get_settings(), "agent_objection_precheck_enabled", enabled)
    response = campus_runtime(None)
    assert response["data"]["objection_precheck"] is enabled
    assert set(response["data"]) == {
        "academic_scoped", "business_scoped", "scheduling", "objection_precheck"
    }
