from datetime import datetime, time, timedelta
from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from app.modules.organization.schemas import StrictModel

CanonicalId = Annotated[str, Field(strict=True, pattern=r"^[1-9][0-9]{0,18}$")]


class WeeklyPlanUpdate(StrictModel):
    current_version: int = Field(strict=True, ge=0)
    enabled: StrictBool
    first_week: int = Field(strict=True, ge=1, le=60)
    last_week: int = Field(strict=True, ge=1, le=60)
    run_weekday: int = Field(strict=True, ge=1, le=7)
    run_time: str = Field(strict=True, pattern=r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
    counts: dict[CanonicalId, Annotated[int, Field(strict=True, ge=1, le=50)]] = Field(
        min_length=1, max_length=100
    )
    course_type_ids: list[CanonicalId] = Field(min_length=1, max_length=100)
    require_photo: StrictBool = True
    publication_mode: Literal["DRAFT_ONLY"] = "DRAFT_ONLY"

    @model_validator(mode="after")
    def bounded(self):
        if self.first_week > self.last_week or sum(self.counts.values()) > 500:
            raise ValueError("有效周次或每周抽查总数无效")
        if len(set(self.course_type_ids)) != len(self.course_type_ids) or any(
            int(value) >= 2**63 for value in [*self.counts, *self.course_type_ids]
        ):
            raise ValueError("班级或课程类型标识无效或重复")
        self.course_type_ids.sort(key=int)
        return self


def weekly_period(semester, configuration, week):
    """UTC trigger in the previous Shanghai week; target dates use teaching-week origin."""
    monday = semester.first_monday + timedelta(weeks=week - 1)
    local_due = datetime.combine(
        monday - timedelta(days=7) + timedelta(days=configuration["run_weekday"] - 1),
        time.fromisoformat(configuration["run_time"]),
    )
    return local_due - timedelta(hours=8), monday, monday + timedelta(days=6)
