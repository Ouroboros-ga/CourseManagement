"""显式正式发布与本人来源读取；不调用管理总课表、不写私人内容。"""

import hashlib
import json
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams
from app.core.exceptions import ConflictError, ErrorCode
from app.modules.academic.publication_models import (
    AcademicPublication,
    PublicationAudience,
    PublishedSchedule,
    PublishedScheduleStudent,
)
from app.modules.academic.publication_repository import (
    AcademicPublicationRepository,
    MyAcademicSourceRepository,
)
from app.modules.audit.models import AuditLog
from app.modules.identity.resource_scope import resolve_scope
from app.modules.identity.service import CurrentUser
from app.modules.organization.service import atomic_write


def fingerprint(value) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class AcademicPublicationService:
    def __init__(self, db: Session, actor: CurrentUser, college_id: int, request_id=None):
        self.db, self.actor, self.college_id = db, actor, college_id
        self.request_id = request_id

    def _source(self, semester_id: int, *, lock: bool):
        scope = resolve_scope(self.db, self.actor, self.college_id, "academic.manage", write=lock)
        repo = AcademicPublicationRepository(self.db, scope)
        context, entries = repo.source(semester_id, lock=lock)
        previous = repo.latest(semester_id)
        content_hash = fingerprint([context, entries])
        revision = fingerprint(
            [
                self.college_id,
                semester_id,
                scope.authorization_revision,
                previous.id if previous else None,
                content_hash,
            ]
        )
        return context, entries, previous, content_hash, revision

    def preview(self, semester_id: int):
        context, entries, previous, content_hash, revision = self._source(semester_id, lock=False)
        return {
            "semester_id": str(semester_id),
            "college_id": str(self.college_id),
            "source_revision": revision,
            "current_version": previous.version if previous else 0,
            "schedule_count": len(entries),
            "student_count": len({sid for _, ids in entries for sid in ids}),
            "changed": previous is None or previous.source_hash != content_hash,
            "semester_name": context["semester_name"],
        }

    @atomic_write
    def publish(self, semester_id: int, source_revision: str):
        context, entries, previous, content_hash, revision = self._source(semester_id, lock=True)
        if source_revision != revision:
            raise ConflictError(
                ErrorCode.VERSION_CONFLICT, "教务资料、授权或发布版本已变化，请重新预览"
            )
        if previous and previous.source_hash == content_hash:
            self.db.commit()
            return {
                "publication_id": str(previous.id),
                "version": previous.version,
                "changed": False,
            }
        row = AcademicPublication(
            college_id=self.college_id,
            semester_id=semester_id,
            version=previous.version + 1 if previous else 1,
            source_hash=content_hash,
            context=context,
            published_by=self.actor.id,
        )
        self.db.add(row)
        self.db.flush()
        by_student = defaultdict(list)
        segments: dict[object, int] = defaultdict(int)
        for snapshot, ids in entries:
            segments[snapshot["source_schedule_id"]] += 1
            published = PublishedSchedule(
                publication_id=row.id,
                source_schedule_id=snapshot["source_schedule_id"],
                segment_no=segments[snapshot["source_schedule_id"]],
                snapshot=snapshot,
            )
            self.db.add(published)
            self.db.flush()
            for sid, dates in ids.items():
                self.db.add(
                    PublishedScheduleStudent(
                        published_schedule_id=published.id, student_id=sid, occurrence_dates=dates
                    )
                )
                by_student[sid].append({**snapshot, "occurrence_dates": dates})
        old_hashes: dict[int, str] = (
            {
                sid: value
                for sid, value in self.db.execute(
                    select(PublicationAudience.student_id, PublicationAudience.content_hash).where(
                        PublicationAudience.publication_id == previous.id
                    )
                )
            }
            if previous
            else {}
        )
        for sid in sorted(set(by_student) | old_hashes.keys()):
            own_hash = fingerprint([context, by_student[sid]])
            self.db.add(
                PublicationAudience(
                    publication_id=row.id,
                    student_id=sid,
                    content_hash=own_hash,
                    changed=old_hashes.get(sid) != own_hash,
                )
            )
        self.db.add(
            AuditLog(
                actor_user_id=self.actor.id,
                action="academic.timetable.publish",
                resource_type="academic_publication",
                resource_id=str(row.id),
                before_json={"version": previous.version if previous else 0},
                after_json={
                    "_workspace_college_id": str(self.college_id),
                    "college_id": str(self.college_id),
                    "semester_id": str(semester_id),
                    "version": row.version,
                    "source_hash": content_hash,
                },
                request_id=self.request_id,
            )
        )
        self.db.commit()
        return {"publication_id": str(row.id), "version": row.version, "changed": True}


class MyAcademicSourceService:
    def __init__(self, db: Session, user_id: int):
        self.db, self.user_id = db, user_id
        self.repo = MyAcademicSourceRepository(db)

    def initialize(self, semester_id: int):
        student = self.repo.bound_student(self.user_id)
        publications, entries, exists = self.repo.own_entries(student.id, semester_id)
        return {
            "semester_id": str(semester_id),
            "status": "AVAILABLE" if entries else ("NO_ENROLLMENT" if exists else "NOT_PUBLISHED"),
            "source_revision": fingerprint(
                [(str(p.id), p.version, p.source_hash) for p in publications]
            ),
            "sources": [
                {
                    "publication_id": str(p.id),
                    "college_id": str(p.college_id),
                    "version": p.version,
                    "published_at": p.created_at.isoformat() + "Z",
                    "calendar": p.context,
                }
                for p in publications
            ],
            "entries": entries,
        }

    def notices(self, params: PageParams):
        from app.modules.academic.notice_feed import personal_notices
        student = self.repo.bound_student(self.user_id)
        return personal_notices(self.db, student.id, params)
