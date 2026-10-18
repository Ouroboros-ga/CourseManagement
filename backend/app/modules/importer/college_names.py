"""仅在同校内唯一时接受学院简称；不按包含关系猜测学院身份。"""

import re
import unicodedata

from sqlalchemy import select

from app.modules.organization.models import College


def normalize_college_name(name: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", name))


def college_name_keys(db, college_id):
    school = select(College.school_id).where(College.id == college_id).scalar_subquery()
    colleges = db.execute(select(College.id, College.name).where(College.school_id == school)).all()
    official = next(name for cid, name in colleges if cid == college_id)
    names: dict[str, set[int]] = {}
    for cid, name in colleges:
        full = normalize_college_name(name)
        for key in (full, re.sub(r"\([^()]*\)$", "", full)):
            names.setdefault(key, set()).add(cid)
    return official, {key for key, ids in names.items() if ids == {college_id}}
