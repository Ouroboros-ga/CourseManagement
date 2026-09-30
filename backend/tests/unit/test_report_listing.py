"""周报发现只以可下载的已发布版本作为最新版本。"""

from datetime import datetime
from types import SimpleNamespace

from app.modules.report.listing import summary_row


def test_summary_uses_published_generation_time_and_source_revision() -> None:
    report = SimpleNamespace(id=12, semester_id=3, week_no=8)
    version = SimpleNamespace(
        id=24, version_no=2, status="PUBLISHED", source_revision=5,
        created_at=datetime(2026, 9, 20, 8), generated_at=datetime(2026, 9, 20, 9),
    )
    assert summary_row(report, version, 6) == {
        "report_id": "12", "semester_id": "3", "week_no": 8,
        "latest_version_id": "24", "latest_version_no": 2,
        "latest_version_created_at": "2026-09-20T09:00:00Z",
        "source_changed": True,
    }


def test_summary_does_not_expose_generating_version() -> None:
    report = SimpleNamespace(id=12, semester_id=3, week_no=8)
    version = SimpleNamespace(id=25, version_no=3, status="GENERATING")
    assert summary_row(report, version, 6)["latest_version_id"] is None
    assert summary_row(report, version, 6)["source_changed"] is False
