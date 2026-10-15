"""Two already published migration branches must converge without rewriting history."""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def test_unified_release_has_one_head_and_keeps_both_published_branches():
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["f26a1015a001"]
    assert script.get_revision("f26a1015d001").down_revision == "f26a1014x001"
    assert script.get_revision("f26a1014x001").down_revision == "f26a1014r001"
    assert script.get_revision("f26a1014r001").down_revision == "f26a1014g001"
    assert script.get_revision("f26a1014g001").down_revision == "f26a1014t001"
    assert script.get_revision("f26a1014t001").down_revision == "f26a1014p001"
    assert script.get_revision("f26a1014p001").down_revision == "f26a1014e001"
    assert script.get_revision("f26a1014e001").down_revision == "f26a1014m001"
    revision = script.get_revision("f26a1014m001")
    assert set(revision.down_revision) == {"f26a1013c002", "181729fc7239"}
    assert script.get_revision("181729fc7239").down_revision == "b2c3d4e5f6a7"
    assert script.get_revision("f26a1013c001").down_revision == "b2c3d4e5f6a7"


def test_branch_specific_rollback_keeps_single_review_history():
    root = Path(__file__).parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    script = ScriptDirectory.from_config(config)
    steps = script._downgrade_revs("f26a1013c002@b2c3d4e5f6a7", ("f26a1013c002", "181729fc7239"))
    assert [step.revision.revision for step in steps] == ["f26a1013c002", "f26a1013c001"]
