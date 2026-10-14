"""Server-authored immutable audit scope; never inferred from today's resource owner."""


def scoped_snapshot(snapshot, college_id):
    if college_id is None:
        return snapshot
    if type(college_id) is not int or not 0 < college_id < 2**63:
        raise ValueError("审计学院标识无效")
    return {**(snapshot or {}), "_workspace_college_id": str(college_id)}
