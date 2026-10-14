"""新配置动作白名单。学院内取并集，不能把不同学院动作交叉合成授权。"""

ACADEMIC_SCOPE_ACTIONS = frozenset(
    {"academic.read", "academic.manage", "student.read", "student.manage", "volunteer.read"}
)

CAMPUS_ACTIONS = ACADEMIC_SCOPE_ACTIONS | frozenset(
    {
        "academic.course_type.read",
        "academic.course_type.manage",
        "volunteer.group.read",
        "volunteer.group.manage",
        "volunteer.member.manage",
        "volunteer.config.publish",
    }
)


def effective_actions(grants, college_id: int, now) -> frozenset[str]:
    return frozenset(
        action
        for grant in grants
        if grant.college_id == college_id
        and grant.status == "ACTIVE"
        and (grant.starts_at is None or grant.starts_at <= now)
        and (grant.expires_at is None or grant.expires_at > now)
        for action in grant.actions
        if action in CAMPUS_ACTIONS
    )
