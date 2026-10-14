"""通用纯判定规则；调用者必须先取得经授权的正式课次/本人课程。"""

from dataclasses import dataclass
from typing import Literal

Effect = Literal["BLOCK", "WARN", "ALLOW"]


@dataclass(frozen=True)
class InspectionScope:
    college_id: int
    course_type_ids: frozenset[int]
    class_ids: frozenset[int] | None = None

    def allows(self, *, college_id: int, course_type_id: int, class_ids: set[int]) -> bool:
        return (
            college_id == self.college_id
            and course_type_id in self.course_type_ids
            and bool(class_ids)
            and (self.class_ids is None or class_ids <= self.class_ids)
        )


def course_conflict_effect(
    own_course_type_id: int | None,
    own_teaching_class_id: int,
    default: Effect,
    type_overrides: dict[int, Effect],
    teaching_class_overrides: dict[int, Effect],
) -> Effect:
    return teaching_class_overrides.get(
        own_teaching_class_id,
        type_overrides.get(own_course_type_id, default)
        if own_course_type_id is not None
        else default,
    )


def assignment_warning_codes(
    config: dict,
    own_class_id: int | None,
    roster_classes: set[int],
    interval: tuple[int, int],
    own_slots,
) -> tuple[str, ...]:
    warnings = []
    if (
        own_class_id is not None
        and own_class_id in roster_classes
        and config["own_class_effect"] == "WARN"
    ):
        warnings.append("SELF_CLASS_WARNING")
    if any(
        interval[0] < end
        and start < interval[1]
        and course_conflict_effect(
            ctype,
            teaching_id,
            config["default_effect"],
            {int(k): v for k, v in config.get("type_overrides", {}).items()},
            {int(k): v for k, v in config.get("teaching_class_overrides", {}).items()},
        )
        == "WARN"
        for start, end, teaching_id, ctype in own_slots
    ):
        warnings.append("OWN_COURSE_WARNING")
    return tuple(warnings)
