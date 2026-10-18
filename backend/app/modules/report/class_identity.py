"""报表内部班级键：冻结 ID 决定身份，名称只负责显示。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ClassIdentity:
    college_id: int | None
    class_id: int | None
    legacy_name: str | None
    name: str | None = field(compare=False)

    @classmethod
    def from_snapshot(cls, college_id, class_id, name):
        return cls(college_id, class_id, name if class_id is None else None, name)


ClassKey = ClassIdentity | str | None
