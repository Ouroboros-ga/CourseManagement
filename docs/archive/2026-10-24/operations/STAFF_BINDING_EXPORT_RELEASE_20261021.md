> 归档说明（2026-10-24）：原路径 `docs/development/STAFF_BINDING_EXPORT_RELEASE_20261021.md`。本文保留当时的计划、验证或发布事实，不代表当前部署状态；后续执行请看[当前实施状态](../../../development/IMPLEMENTATION_STATUS.md)。

# 教师绑定码 Excel 导出发布记录

教师档案支持批量生成绑定码并下载 Excel，复用学生表格样式与下载工具。教师凭工号和一次性码绑定已有档案；不新建另一套账号，不改变管理角色、授课关系或责任班级。

- 功能提交：`fed8518`；最终应用源码：`145dfe8fc12ee9b7426550d738de857abc6a97fc`，已推送 `origin/dev-main`。已合并 `eb30c03` 的账号候选分页及此前统一样式，未覆盖线上更新。
- 正式域名：`https://course.zsitai.xyz`，服务器 `101.34.52.163`。
- 后端和Web发布名：`20261021-staff-binding-export-145dfe8fc1`，切换时间 `2026-10-21T10:35:43Z`（北京时间18:35）。
- 后端目录：`/opt/course-management/releases/20261021-staff-binding-export-145dfe8fc1`；Web目录：`/opt/course-management/admin-web/releases/20261021-staff-binding-export-145dfe8fc1`。

入口：教职工档案 → 批量生成绑定码并导出 Excel。可按当前关键词筛选所有分页的在职未关联人员，或仅勾选本页人员；有效期默认30天，可选14/60/90天，单次最多500人，超过后明确要求分批。包含工号、姓名、学院、绑定码和北京时间截止日期。构建文件成功后统一提交凭证及审计，失败回滚；明文不写审计。

验证证据：12项导出/共享表格/学院权限用例、22项原身份回归、7项学院OpenAPI契约通过；最终合并版本4项前端用例、类型检查与构建通过。后端变更文件Mypy和Ruff通过。Edge本地虚构数据验证勾选、有效期、字符串BIGINT与下载。候选与正式服务均就绪；新导出端点匿名POST返回401。550个源码/工具文件、70个Web文件及公网首页与3个入口资源哈希匹配，nginx配置检查通过，服务active。

发布前源码核对无偏移。数据库版本保持 `f26a1019s007`，配置SHA-256保持 `e906579ee8e72a4d3f98007c11f87d3530a98e5c4e7beb37fde5efd50bf53163`。未执行迁移、seed、真实绑定码签发或其他业务数据改写。未以匿名探针替代教师真机绑定验收。

回退证据位于 `/var/backups/course-management/20261021-staff-binding-export-145dfe8fc1/`，包含 `before.json`、`report.json`、配置备份、发布清单和 `rollback.py`。此前后端为 `20261021-student-staff-fix-2c0c7a7cff`，此前Web为 `20261021-ui-unify-eb30c03`。如需回退，在服务器执行 `python3 /var/backups/course-management/20261021-staff-binding-export-145dfe8fc1/rollback.py --apply`，恢复两个发布指针并重启检查。此命令仅记录，本轮没有执行回退或数据库恢复。
