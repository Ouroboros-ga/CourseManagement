"""计划生效投影维护：python -m app.modules.academic.apply_enrollment_changes。"""

from app.core.database import get_session_factory
from app.modules.academic.enrollment_service import EnrollmentService


def main():
    with get_session_factory()() as db:
        count = EnrollmentService(db).apply_due()
        print(f"applied={count}")


if __name__ == "__main__":
    main()
