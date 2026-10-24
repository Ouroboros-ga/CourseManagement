> 归档说明（2026-10-24）：原路径 `docs/development/STAFF_IMPORT_ROUTING_RELEASE.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 教职工档案预览类型修复与发布

日期：2026-10-19；服务器 `101.34.52.163`；测试入口 `https://test.zsitai.xyz`。

## 触发与行为

统一入口正确识别 `faculty_staff`，但 Web 的学院动作目录缺少 `staff.manage`，会将学院授予的该能力误当作全局权限查询，得到不可用。内层导入向导随后静默选择第一项可用类型 `grid_timetable`。现场最近一份教职工测试文件的预览目标确为 `grid_timetable`，最终显示“网格课表解析失败：Excel xlsx file; not supported”。

修复在学院动作目录补齐 `staff.manage`，让现有会话逻辑按所选学院能力判断。分组内指定类型不可用时不再退回其他解析器，而是禁用读取并显示权限提示。服务端授权及档案字段规则保持原样。

旧预览不会改变类型；用户须刷新页面并重新读取文件。没有读取用户原始 Excel 内容，尚未确认该文件是否满足教职工档案字段要求；临时工号后台初始化流程不因本次修复改变。

## 本次验证

- 3 个新增回归用例在修改前均失败，分别复现学院教职工权限误判、教职工文件流入课表预览、不可用分组静默退回课表；修改后通过。
- 导入、会话相关测试共 16 项通过；全量前端测试 109 通过、1 失败。失败为 `workspace-pages.test.mjs` 的课表夹具没有提供 `useDispatchOptions`；在独立 HEAD 基线副本复现同样失败，未关闭或修改该测试。
- `npm.cmd run build` 通过，含 Vue TypeScript 检查；常规构建体积提示保留。`git diff --check` 通过。
- 已亲自检查差异；未调用子 agent。

## 发布与回滚

- 功能提交：`72fcb8614f8b403179bd57ab7e7de0b7cc651f69`，已推送 `origin/dev-main`。
- 新 Web：`/opt/course-management/admin-web/releases/20261019-staff-import-72fcb86`。
- 旧 Web/回滚目标：`/opt/course-management/admin-web/releases/20261019-member-onboarding-fe626e3d9d`。
- 后端仍为 `/opt/course-management/releases/20261019-import-weeks-98966f4a3e`。
- 配置 SHA-256 保持 `d2f5e55e658c04a180568b62b8a959ec21b43f8969285856555fdf30265dc18f`。

发布包与清单逐文件核验后原子切换 Web 指针，保留旧哈希资源供未刷新的页面按需加载。通过正常 DNS/TLS 访问并核验全部 67 个新文件 SHA-256，`nginx -t`、服务 active、公网数据库就绪均通过。浏览器刷新测试登录页，确认账号、密码和登录按钮正常渲染；没有真实账号登录或代用户提交导入。

私有备份目录 `/var/backups/course-management/20261019T134311Z-staff-import-web` 保存旧指针、发布清单、脚本和报告。发布脚本失败时自动切回旧指针；实际验证成功，未执行回滚。人工回滚可将 `/opt/course-management/admin-web/current` 原子切回上述旧 Web 目录，无需数据库恢复或后端重启。
