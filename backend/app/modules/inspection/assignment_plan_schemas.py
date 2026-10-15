from pydantic import Field, model_validator

from app.modules.inspection.group_sampling import GroupAssignRequest
from app.modules.organization.schemas import StrictModel


class AssignmentPlanPreview(GroupAssignRequest):
    assignments: dict[str, str] | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def explicit_assignments(self):
        if self.assignments is not None:
            if set(self.assignments) != set(self.task_ids) or any(
                not value.isascii() or not value.isdigit() or not 0 < int(value) < 2**63
                for value in self.assignments.values()
            ):
                raise ValueError("人工计划须明确每项任务及有效志愿者ID")
        return self


class WarningConfirmation(StrictModel):
    task_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    volunteer_user_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")
    warning_codes: list[str] = Field(max_length=10)


class AssignmentPlanCommit(StrictModel):
    revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirmations: list[WarningConfirmation] = Field(default_factory=list, max_length=500)
