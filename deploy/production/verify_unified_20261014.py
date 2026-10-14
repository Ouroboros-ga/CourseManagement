"""Read-only acceptance of the unified build under the runtime database account."""
import importlib.util
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.getcwd())

from app.core.config import get_settings
from app.core.database import get_engine
from app.main import create_app
from sqlalchemy import text

spec = importlib.util.spec_from_file_location("photo_acceptance", "/tmp/cm-verify-photo-time.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.live(False)
settings = get_settings()
assert not settings.campus_configuration_enabled and not settings.campus_academic_scoped_enabled
schema = create_app().openapi()
assert "/api/v1/objections/{objection_id}/review" in schema["paths"]
assert schema["paths"]["/api/v1/objections/{objection_id}/initial-review"]["post"]["deprecated"]
with get_engine().connect() as db:
    assert db.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "f26a1014m001"
    for table in ["school", "college", "scoped_grant", "course_type", "volunteer_group",
                  "group_config_version", "group_scope_type"]:
        assert db.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar_one() == 0
    db.execute(text("SELECT college_id, ownership_version FROM inspection_task LIMIT 1")).first()
web = Path("/opt/course-management/admin-web/current")
sources = [p.read_text() for p in (web / "assets").glob("*.js") if "pt20261014" not in p.name]
assert any("Asia/Shanghai" in source for source in sources)
assert any("/review" in source for source in sources)
assert any("objection.final_review" in source for source in sources)
print(json.dumps({"single_review_route": True, "merged_schema": True,
                  "runtime_new_tables_readable": True, "college_flags_off": True,
                  "web_timezone_and_single_review": True}))
