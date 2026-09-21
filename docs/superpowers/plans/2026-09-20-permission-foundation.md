# Permission Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已确认的 38 项权限、五角色默认矩阵及教师角色管理边界落实为可测试的后端策略基础。

**Architecture:** 保留模块化单体。core 定义稳定 code；identity/policy.py 保存默认映射与纯授权判断，后续管理服务消费它并负责范围、事务及审计。本批只交付纯策略，不修改数据库授权，不开放管理接口。

**Tech Stack:** Python 3.12、StrEnum、pytest、ruff、mypy；后续持久化沿用 SQLAlchemy 2.x/MySQL。

## Global Constraints

- 固定五角色、38 个 Permission；不新增 assignment.read。
- 教师手工角色允许列表仅 STUDENT_AFFAIRS_MANAGER；TEACHER_ADMIN / SUPER_ADMIN 仅超管管理。
- STUDENT / VOLUNTEER 由有效绑定与学期资格维护；超管也不能用角色编辑旁路赋予执行资格。
- 负责人三个个人可选项默认关闭；教师和超管按矩阵默认具备对应管理能力。
- 权限 code 不代替资源范围、受限会话、状态与版本检查。
- 本文是待执行计划。本轮不改应用代码、不赋权、不提交。实施时检查所需技能是否可用；不能把标题中的技能引用当成已加载或必须启动子代理。
- 以下命令在 `D:\My project\CourseManagement\backend` 执行；提交检查点仅在获得提交指令后执行，且只暂存本任务文件，禁止 `git add .`。

---

## 文件与接口

| 文件 | 责任 |
|---|---|
| 修改 `backend/app/core/permissions.py` | 补齐 PermissionCode；保留 RoleCode |
| 新建 `backend/app/modules/identity/policy.py` | 默认矩阵及角色差集纯判断，无数据库访问 |
| 新建 `backend/tests/unit/test_permission_policy.py` | 权限集合、默认矩阵、角色变更边界 |

来源：[权限策略第 4–6 节](../../PERMISSIONS.md)。测试期望值应独立录入自文档，不能从被测映射复制后断言自身相等。

## Task 1：权限注册表与默认矩阵

**Interfaces:** 消费已有 `RoleCode` / `PermissionCode`；产出 `DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]]`、`OPTIONAL_PERMISSION_CODES: frozenset[str]`。后续种子及授权读取使用同一映射，禁止重复维护另一套默认值。

- [ ] 在 `test_permission_policy.py` 编写注册表与角色矩阵测试。以下为关键断言，另将 PERMISSIONS.md 第 5 节五列中每个“是”逐项录入各角色的独立期望集合并断言集合相等；“可选”“条件派生”不放入默认集合。

```python
from app.core.permissions import PermissionCode, RoleCode
from app.modules.identity.policy import (
    DEFAULT_ROLE_PERMISSIONS, OPTIONAL_PERMISSION_CODES,
)

def test_registry_and_manager_defaults():
    assert len(PermissionCode) == 38
    assert "assignment.read" not in {p.value for p in PermissionCode}
    assert set(DEFAULT_ROLE_PERMISSIONS) == {r.value for r in RoleCode}
    assert DEFAULT_ROLE_PERMISSIONS["STUDENT_AFFAIRS_MANAGER"] == frozenset({
        "identity.binding.manage", "student.read", "inspection.read",
        "inspection.roster.read", "submission_deadline.read", "attendance.read",
    })
    assert OPTIONAL_PERMISSION_CODES == frozenset({
        "statistics.read", "report.read", "objection.initial_review",
    })
    for codes in DEFAULT_ROLE_PERMISSIONS.values():
        assert codes <= {p.value for p in PermissionCode}

def test_admin_has_no_automatic_actor_permissions():
    for role in ("SUPER_ADMIN", "TEACHER_ADMIN"):
        assert not DEFAULT_ROLE_PERMISSIONS[role] & {
            "submission.create", "assignment.change_request", "objection.create",
        }
```

- [ ] 执行 `uv run pytest tests/unit/test_permission_policy.py -q`，确认因缺少 policy/完整注册表失败，而非环境故障。
- [ ] 按基线第 4 节逐项补 enum，成员名采用 code 大写并将点替换成下划线（保留现有三个名字）。在 `policy.py` 写入下列映射。这里的集合减法仅用于显式矩阵，不代表超管运行时绕过业务守卫。

```python
from app.core.permissions import PermissionCode, RoleCode

OPTIONAL_PERMISSION_CODES = frozenset({
    "statistics.read", "report.read", "objection.initial_review",
})
_admin = frozenset(p.value for p in PermissionCode) - {
    "assignment.change_request", "submission.create", "objection.create",
}
DEFAULT_ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    RoleCode.SUPER_ADMIN.value: _admin,
    RoleCode.TEACHER_ADMIN.value: _admin - {
        "account.read", "account.manage", "audit.read",
        "system.config.read", "system.config.manage",
    },
    RoleCode.STUDENT_AFFAIRS_MANAGER.value: frozenset({
        "identity.binding.manage", "student.read", "inspection.read",
        "inspection.roster.read", "submission_deadline.read", "attendance.read",
    }),
    RoleCode.VOLUNTEER.value: frozenset({
        "inspection.read", "inspection.roster.read", "assignment.change_request",
        "submission.create", "submission.read",
    }),
    RoleCode.STUDENT.value: frozenset({
        "attendance.read", "objection.create", "objection.read",
    }),
}
```

- [ ] 再运行同一测试，确认五列完整集合、38 项精确 code 以及上述断言通过；不能只凭数量正确验收。
- [ ] 检查差异只包含三个计划文件，记录检查点 `feat: define permission registry and role defaults`。本批不执行 seed，不更改现有账号角色。

## Task 2：角色变更差集策略

**Interfaces:** 在同一 `policy.py` 产出 `can_change_roles(actor_roles: frozenset[str], current_roles: frozenset[str], desired_roles: frozenset[str]) -> bool`。输入必须来自后续服务的可信身份/锁定目标；返回值只判定角色类型边界，不判定学院范围或 Permission。未知 code 返回 False，API schema 另将未知 code 映射为 422。

- [ ] 在同一测试文件加入以下参数化测试，并补充教师撤销自己教师角色、完整集合省略 SUPER_ADMIN、无管理角色、无变化请求、未知 code、混合合法与非法变更用例。自身与他人的角色边界一致，故本纯函数不需要 user_id；自我可选权限提权由管理服务单独拦截。

```python
import pytest
from app.modules.identity.policy import can_change_roles

@pytest.mark.parametrize("actor,current,desired,expected", [
    ({"TEACHER_ADMIN"}, set(), {"TEACHER_ADMIN"}, False),
    ({"TEACHER_ADMIN"}, {"TEACHER_ADMIN"}, set(), False),
    ({"TEACHER_ADMIN"}, set(), {"STUDENT_AFFAIRS_MANAGER"}, True),
    ({"TEACHER_ADMIN"}, {"STUDENT_AFFAIRS_MANAGER"}, set(), True),
    ({"SUPER_ADMIN"}, set(), {"TEACHER_ADMIN"}, True),
    ({"SUPER_ADMIN"}, {"TEACHER_ADMIN"}, set(), True),
    ({"SUPER_ADMIN"}, set(), {"VOLUNTEER"}, False),
    ({"TEACHER_ADMIN"}, {"STUDENT"}, {"STUDENT", "STUDENT_AFFAIRS_MANAGER"}, True),
    ({"TEACHER_ADMIN"}, {"STUDENT"}, {"STUDENT_AFFAIRS_MANAGER"}, False),
])
def test_role_change_boundary(actor, current, desired, expected):
    assert can_change_roles(
        frozenset(actor), frozenset(current), frozenset(desired),
    ) is expected
```

- [ ] 执行 `uv run pytest tests/unit/test_permission_policy.py -q`，确认因缺少函数失败。
- [ ] 在 `policy.py` 实现以下纯策略；原样保留受保护角色可以通过，改变它们不能通过。多角色操作者若真实拥有超管角色，按超管能力处理。

```python
def can_change_roles(
    actor_roles: frozenset[str],
    current_roles: frozenset[str],
    desired_roles: frozenset[str],
) -> bool:
    known = frozenset(r.value for r in RoleCode)
    if not (actor_roles | current_roles | desired_roles) <= known:
        return False
    changed = current_roles ^ desired_roles
    if changed & {"STUDENT", "VOLUNTEER"}:
        return False
    if "SUPER_ADMIN" in actor_roles:
        return True
    if "TEACHER_ADMIN" in actor_roles:
        return changed <= {"STUDENT_AFFAIRS_MANAGER"}
    return False
```

- [ ] 运行 `uv run pytest tests/unit/test_permission_policy.py -q`、`uv run ruff check app/core/permissions.py app/modules/identity/policy.py tests/unit/test_permission_policy.py`、`uv run mypy app`。期望退出码均为 0；如已有无关失败，记录具体位置，不扩大修改范围或声称全绿。
- [ ] 检查差异并记录检查点 `feat: restrict teacher role changes to affairs managers`；需要提交时仅暂存本任务文件。

## 交付边界与下一批

首批交付仅是可复用、已单测的策略。没有管理 API、事务和审计时，不能说“角色权限已全面生效”。下一批按 [开发路线 P1 第 2–7 步](../../DEVELOPMENT_PLAN.md) 实现种子同步、测试库保护、审计迁移、角色与个人开关服务及 API，并用真实 MySQL 验证并发和回滚。

规划自查：38 项来源为权限基线；矩阵包含全部五角色；教师新增/删除受保护角色均覆盖；STUDENT/VOLUNTEER 防旁路覆盖；所有接口名称和文件路径在本文定义。数据库、微信、行级范围与前端明确属于后续阶段，未冒充本批完成。
