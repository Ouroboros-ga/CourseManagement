> 归档说明（2026-10-24）：原路径 `docs/development/TEST_WEB_REFRESH_ORIGIN_RELEASE.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 测试站点登录刷新来源配置修复

日期：2026-10-19。目标服务器：`101.34.52.163`；入口：`https://test.zsitai.xyz`。

## 原因与修复

用户确认导入时业务请求返回 401，Web 随后自动调用 `/api/v1/auth/refresh`，但返回 403。现场使用无效诊断 Cookie、测试站点 Origin 与 `Sec-Fetch-Site: same-origin` 复现响应码 `CSRF_FAILED`。服务器 `CSRF_ALLOWED_ORIGINS` 只有 `https://course.zsitai.xyz`，没有测试域名。

仅在 `/etc/course-management/backend.env` 原有白名单追加 `https://test.zsitai.xyz`，随后重启 `course-management`。保留正式来源及所有 CSRF 检查；没有修改业务代码、放宽为任意来源或延长令牌有效期。环境配置示例补充实际 Web 来源填写说明。

## 验证

公网 TLS 请求 `/api/v1/auth/refresh`，均携带无效诊断 Cookie，无真实用户凭证：

| Origin | Sec-Fetch-Site | 修复后结果 |
| --- | --- | --- |
| `https://test.zsitai.xyz` | `same-origin` | 401 `UNAUTHENTICATED`，已通过来源校验并进入凭证校验 |
| `https://course.zsitai.xyz` | `same-origin` | 401 `UNAUTHENTICATED` |
| `https://invalid.example` | `same-origin` | 403 `CSRF_FAILED` |
| `https://test.zsitai.xyz` | `cross-site` | 403 `CSRF_FAILED` |

服务 active，`nginx -t` 通过，公网 `/health/ready` 返回 200、`database=up`。修复前后正式 `course_schedule` 和 `faculty_staff` 数量均为 0，未代替用户执行真实导入。

后端指针仍为 `/opt/course-management/releases/20261019-import-weeks-98966f4a3e`；Web 指针仍为 `/opt/course-management/admin-web/releases/20261019-member-onboarding-fe626e3d9d`。本次为运行配置修复，未发布新的应用包或迁移。

未使用真实登录凭证测试轮换、业务重试或真实课表写入。用户须重新登录测试站点后再次确认导入；若预览已失效，再重新读取资料。

## 备份与回滚

私有备份目录：`/var/backups/course-management/20261019T132206Z-test-refresh-origin`，包含原 `backend.env`、修复脚本及 `report.json`。修复脚本在验证失败时自动恢复配置并重启，现场验证成功，未触发回滚。

- 修改前环境配置 SHA-256：`678a9748d26d739c587d22243264d0b9216e33ba0f1d8f37af83bdd005690a03`。
- 修改后环境配置 SHA-256：`d2f5e55e658c04a180568b62b8a959ec21b43f8969285856555fdf30265dc18f`。

必要时以 root 恢复上述备份目录的 `backend.env` 到 `/etc/course-management/backend.env`，再重启 `course-management` 并验证健康。该回滚会重新阻断测试域名的 Cookie 刷新，只用于配置恢复，不恢复数据库。
