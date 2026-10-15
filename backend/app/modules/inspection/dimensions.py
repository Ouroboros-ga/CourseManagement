"""Optional query dimensions narrow visibility; they never grant data access."""

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import select

from app.modules.inspection.models import InspectionTask, TaskScheduleSource


@dataclass(frozen=True)
class TaskDimensions:
    course_type_id: int | None = None
    group_id: int | None = None
    teaching_class_id: int | None = None

    def conditions(self):
        result = []
        if self.course_type_id is not None:
            result.append(InspectionTask.course_type_id_snapshot == self.course_type_id)
        if self.group_id is not None:
            result.append(InspectionTask.group_id == self.group_id)
        if self.teaching_class_id is not None:
            result.append(
                (InspectionTask.teaching_class_id == self.teaching_class_id)
                | select(TaskScheduleSource.task_id)
                .where(
                    TaskScheduleSource.task_id == InspectionTask.id,
                    TaskScheduleSource.teaching_class_id == self.teaching_class_id,
                )
                .exists()
            )
        return result


Id = Annotated[int | None, Query(gt=0, le=2**63 - 1)]


def task_dimensions(course_type_id: Id = None, group_id: Id = None, teaching_class_id: Id = None):
    return TaskDimensions(course_type_id, group_id, teaching_class_id)


DimensionsDep = Annotated[TaskDimensions, Depends(task_dimensions)]
