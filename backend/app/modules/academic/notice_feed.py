"""One personal notice list; published updates and enrollment events share pagination."""

from sqlalchemy import String, cast, func, literal, select, union_all

from app.modules.academic.enrollment_models import EnrollmentChange, StudentEnrollment
from app.modules.academic.models import Semester
from app.modules.academic.publication_models import AcademicPublication, PublicationAudience
from app.modules.identity.role_scope import business_today


def personal_notices(db, student_id, params):
    published = (
        select(
            cast(AcademicPublication.id, String).label("id"),
            AcademicPublication.college_id.label("college_id"),
            AcademicPublication.semester_id.label("semester_id"),
            AcademicPublication.version.label("version"),
            AcademicPublication.created_at.label("published_at"),
            literal("ACADEMIC_PUBLICATION").label("kind"),
            (Semester.name + literal("教务课表更新")).label("title"),
            literal("本人相关教务课表已发布更新；已保存的个人课表不会自动修改。").label("message"),
        )
        .join(PublicationAudience, PublicationAudience.publication_id == AcademicPublication.id)
        .join(Semester, Semester.id == AcademicPublication.semester_id)
        .where(PublicationAudience.student_id == student_id, PublicationAudience.changed.is_(True))
    )
    transfers = (
        select(
            (literal("enrollment:") + cast(EnrollmentChange.id, String)).label("id"),
            StudentEnrollment.college_id.label("college_id"),
            literal(None).label("semester_id"),
            literal(0).label("version"),
            EnrollmentChange.created_at.label("published_at"),
            literal("ENROLLMENT_SOURCE_CHANGED").label("kind"),
            literal("教务归属变化").label("title"),
            literal("你的教务归属已变化，个人课表不会自动更新。").label("message"),
        )
        .join(StudentEnrollment, StudentEnrollment.id == EnrollmentChange.target_enrollment_id)
        .where(
            EnrollmentChange.student_id == student_id,
            EnrollmentChange.kind == "TRANSFER",
            EnrollmentChange.state.in_(["SCHEDULED", "APPLIED"]),
            EnrollmentChange.effective_date <= business_today(),
            StudentEnrollment.college_id.is_not(None),
        )
    )
    feed = union_all(published, transfers).subquery()
    total = db.scalar(select(func.count()).select_from(feed)) or 0
    rows = db.execute(
        select(feed)
        .order_by(feed.c.published_at.desc(), feed.c.kind, feed.c.id.desc())
        .offset(params.offset)
        .limit(params.limit)
    ).mappings()
    return {
        "items": [
            {
                **dict(row),
                "college_id": str(row["college_id"]),
                "semester_id": str(row["semester_id"]) if row["semester_id"] is not None else None,
                "published_at": row["published_at"].isoformat() + "Z",
            }
            for row in rows
        ],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
