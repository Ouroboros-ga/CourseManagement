"""正式课次名单统一复用批量日期索引；个人课表不作为业务输入。"""

from datetime import date

from sqlalchemy.orm import Session

from app.modules.academic.models import Student
from app.modules.academic.roster_index import RosterIndex


def rosters_at(
    session: Session, teaching_class_ids: list[int], on_date: date
) -> dict[int, list[Student]]:
    return RosterIndex(session, teaching_class_ids).at(on_date)


def roster_at(session: Session, teaching_class_id: int, on_date: date) -> list[Student]:
    return rosters_at(session, [teaching_class_id], on_date).get(teaching_class_id, [])
