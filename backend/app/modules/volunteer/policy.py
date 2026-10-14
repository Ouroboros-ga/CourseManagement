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
    own_course_type_id: int,
    own_teaching_class_id: int,
    default: Effect,
    type_overrides: dict[int, Effect],
    teaching_class_overrides: dict[int, Effect],
) -> Effect:
    return teaching_class_overrides.get(
        own_teaching_class_id,
        type_overrides.get(own_course_type_id, default),
    )
