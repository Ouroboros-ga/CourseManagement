"""Human explanations are optional; business fields and length limits remain enforced."""

import pytest
from app.modules.attendance.schemas import AttendanceCorrectionRequest
from app.modules.inspection.schemas import (
    ChangeRequestCreateRequest,
    DeadlineDayUpdateRequest,
    ExpectedCountUpdateRequest,
    RosterVersionCreateRequest,
    TaskCancelRequest,
)
from app.modules.objection.schemas import ObjectionCreateRequest
from pydantic import ValidationError


@pytest.mark.parametrize(
    ("schema", "payload"),
    [
        (ChangeRequestCreateRequest, {"assignment_id": 1}),
        (TaskCancelRequest, {"lock_version": 0}),
        (RosterVersionCreateRequest, {"student_ids": [1], "lock_version": 0}),
        (DeadlineDayUpdateRequest, {"time": "22:00", "lock_version": 1}),
        (ExpectedCountUpdateRequest, {"expected_count_current": 30, "lock_version": 0}),
        (AttendanceCorrectionRequest, {"attendance_type": "NORMAL", "current_version": 1}),
        (ObjectionCreateRequest, {"desired_type": "NORMAL"}),
    ],
)
def test_reason_can_be_omitted_or_empty_but_remains_bounded(schema, payload):
    assert schema.model_validate(payload).reason == ""
    assert schema.model_validate({**payload, "reason": ""}).reason == ""
    with pytest.raises(ValidationError):
        schema.model_validate({**payload, "reason": "x" * 513})
    with pytest.raises(ValidationError):
        schema.model_validate({"reason": ""})
