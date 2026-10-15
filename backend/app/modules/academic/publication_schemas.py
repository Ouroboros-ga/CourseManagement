"""正式来源 API；不接受客户端 student_id 或个人课表内容。"""

from typing import Literal

from pydantic import Field

from app.modules.organization.schemas import StrictModel


class PublishRequest(StrictModel):
    source_revision: str = Field(pattern=r"^[a-f0-9]{64}$")


class InitializeRequest(StrictModel):
    semester_id: str = Field(pattern=r"^[1-9][0-9]{0,18}$")


class PublishPreview(StrictModel):
    semester_id: str
    college_id: str
    source_revision: str
    current_version: int
    schedule_count: int
    student_count: int
    changed: bool
    semester_name: str


class PublishResult(StrictModel):
    publication_id: str
    version: int
    changed: bool


class SourceEntry(StrictModel):
    source_schedule_id: str
    teaching_class_id: str
    college_id: str
    course_name: str
    class_name: str
    teacher: str | None
    classroom: str | None
    weekday: int
    week_nos: list[int]
    start_period: int
    end_period: int
    start_time: str
    end_time: str
    occurrence_dates: list[str] = Field(default_factory=list)


class PublishedSource(StrictModel):
    publication_id: str
    college_id: str
    version: int
    published_at: str
    calendar: dict


class InitializeResult(StrictModel):
    semester_id: str
    status: Literal["AVAILABLE", "NO_ENROLLMENT", "NOT_PUBLISHED"]
    source_revision: str
    sources: list[PublishedSource]
    entries: list[SourceEntry]


class AcademicNotice(StrictModel):
    kind: Literal["ACADEMIC_PUBLICATION", "ENROLLMENT_SOURCE_CHANGED"] = "ACADEMIC_PUBLICATION"
    id: str
    college_id: str
    semester_id: str | None
    version: int
    published_at: str
    title: str
    message: str


class NoticePage(StrictModel):
    items: list[AcademicNotice]
    total: int
    page: int
    page_size: int


class PreviewEnvelope(StrictModel):
    data: PublishPreview
    requestId: str | None


class PublishEnvelope(StrictModel):
    data: PublishResult
    requestId: str | None


class InitializeEnvelope(StrictModel):
    data: InitializeResult
    requestId: str | None


class NoticeEnvelope(StrictModel):
    data: NoticePage
    requestId: str | None
