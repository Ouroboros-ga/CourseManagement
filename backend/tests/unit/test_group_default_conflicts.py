import pytest
from app.modules.organization.schemas import GroupPublish
from app.modules.volunteer.policy import course_conflict_effect
from pydantic import ValidationError


@pytest.mark.parametrize("field", ["type_overrides", "teaching_class_overrides"])
def test_new_publications_reject_individual_course_exceptions(field):
    with pytest.raises(ValidationError, match="默认课程冲突处理"):
        GroupPublish.model_validate(
            {"lock_version": 1, "course_type_ids": ["1"], field: {"2": "ALLOW"}}
        )


@pytest.mark.parametrize("effect", ["BLOCK", "WARN", "ALLOW"])
def test_default_applies_to_every_course_type_and_class(effect):
    body = GroupPublish.model_validate(
        {"lock_version": 1, "course_type_ids": ["1"], "default_effect": effect}
    )
    for course_type in (None, 1, 2, 999):
        for teaching_class in (1, 2):
            assert (
                course_conflict_effect(course_type, teaching_class, body.default_effect, {}, {})
                == effect
            )


def test_frozen_legacy_versions_keep_their_original_meaning():
    assert course_conflict_effect(2, 3, "BLOCK", {2: "ALLOW"}, {}) == "ALLOW"
    assert course_conflict_effect(2, 3, "ALLOW", {}, {3: "BLOCK"}) == "BLOCK"
