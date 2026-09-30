# API 路由索引

截至 2026-09-29 的代码快照：由 `backend/app/main.py` 注册路由的 OpenAPI 导出核对，共 **92 个路径、112 个操作**。完整请求／响应 schema 见 [openapi.json](./openapi.json)；业务语义见 [API_CONTRACT.md](./API_CONTRACT.md)，角色权限矩阵与数据范围原则见 [PERMISSIONS.md](./PERMISSIONS.md) 第 12 节及 [PERMISSIONS_IMPLEMENTATION.md](./PERMISSIONS_IMPLEMENTATION.md)。本表的权限栏列入口守卫或服务层组合条件；具体可见行、历史快照与防枚举规则由对应 Service 决定。`/api/v1` 是业务前缀，`/health` 是健康检查。OpenAPI 由当前本地代码导出；部分运行时响应信封、鉴权或业务错误并未完整反映在 schema 中，冲突时以实际路由／Service 与 [API_CONTRACT.md](./API_CONTRACT.md) 为准。它不能代替生产联调或验收。

周报边界：V1 仅允许 `scope=COLLEGE`，`CLASS` 请求返回 422，不产生冒称班级的全院报表。周报业务内容仅为考勤汇总；任务总数、未完成、逾期清单属于独立统计接口。影响考勤汇总的有效变更推进周报源修订，任务新建、取消及逾期结算本身不推进。`GET /reports` 已提供学院周报主记录发现；固定格式 Word 仍待实现。生成超规模会先留下 `GENERATING` 记录，再转 `FAILED`，版本号保留。

刷新机器可读 schema（在 `backend` 目录运行，仅读取路由定义，不连接数据库；请勿将运行环境的配置或密钥写入文档）：

```powershell
.venv\Scripts\python.exe -c "import json; from pathlib import Path; from app.main import create_app; Path('../docs/openapi.json').write_text(json.dumps(create_app().openapi(), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')"
```

| 方法 | 实际完整路径 | 功能（路由函数） | 权限／条件 | 数据范围要点 |
|---|---|---|---|---|
| `GET` | `/health/live` | 存活检查 (`live`) | `公开` | — |
| `GET` | `/health/ready` | 数据库就绪检查 (`ready`) | `公开` | — |
| `POST` | `/api/v1/auth/web/login` | Web 账号登录 (`web_login`) | `公开` | — |
| `POST` | `/api/v1/auth/wechat/login` | 微信 code 登录 (`wechat_login`) | `公开；需微信登录开关` | 微信身份定位或新建受限账号 |
| `POST` | `/api/v1/auth/refresh` | 轮换刷新凭证 (`refresh`) | `refresh Cookie 或 JSON 凭证` | 仅当前 refresh 族 |
| `POST` | `/api/v1/auth/logout` | 撤销当前会话 (`logout`) | `有效会话` | 仅当前会话 |
| `GET` | `/api/v1/me` | 读取当前身份与权限 (`me`) | `有效会话` | 仅本人 |
| `POST` | `/api/v1/me/student-binding` | 本人绑定学生 (`bind_student`) | `受限会话／本人绑定` | 仅本人；一次性码 |
| `GET` | `/api/v1/role-assignment-targets` | 角色分配目标 (`role_assignment_targets`) | `role.assign` | 可分配目标及角色边界 |
| `PUT` | `/api/v1/users/{user_id}/roles` | 替换角色集合 (`assign_roles`) | `role.assign` | 目标与角色差集边界 |
| `GET` | `/api/v1/optional-permission-targets` | 可选授权目标 (`optional_permission_targets`) | `optional_permission.manage` | 仅负责人目标 |
| `PUT` | `/api/v1/users/{user_id}/optional-permissions/{code}` | 设置个人可选权限 (`set_optional_permission`) | `optional_permission.manage` | 仅负责人；禁止自我提权 |
| `POST` | `/api/v1/students/{student_id}/binding-tokens` | 签发绑定码 (`issue_binding_token`) | `identity.binding.manage` | 指定学生 |
| `POST` | `/api/v1/binding-tokens/{token_id}/revoke` | 作废绑定码 (`revoke_binding_token`) | `identity.binding.manage` | 指定绑定码 |
| `POST` | `/api/v1/users/{user_id}/student-binding-reset` | 解绑／换绑学生 (`student_binding_reset`) | `identity.binding.manage` | 指定账号；撤销旧会话 |
| `POST` | `/api/v1/academic/semesters` | 创建学期 (`create_semester`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/semesters` | 学期列表 (`list_semesters`) | `academic.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/semesters/{semester_id}` | 更新学期 (`update_semester`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/semesters/{semester_id}` | 学期详情 (`get_semester`) | `academic.read` | 按资源及学期范围 |
| `PUT` | `/api/v1/academic/semesters/{semester_id}/period-definitions/{period_no}` | 新增／更新节次 (`upsert_period_definition`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/semesters/{semester_id}/period-definitions` | 节次列表 (`list_period_definitions`) | `academic.read` | 按资源及学期范围 |
| `DELETE` | `/api/v1/academic/semesters/{semester_id}/period-definitions/{period_id}` | 删除节次 (`delete_period_definition`) | `academic.manage` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/semesters/{semester_id}/calendar-overrides` | 创建校历例外 (`create_calendar_override`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/semesters/{semester_id}/calendar-overrides` | 校历例外列表 (`list_calendar_overrides`) | `academic.read` | 按资源及学期范围 |
| `DELETE` | `/api/v1/academic/semesters/{semester_id}/calendar-overrides/{override_id}` | 删除校历例外 (`delete_calendar_override`) | `academic.manage` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/administrative-classes` | 创建行政班 (`create_admin_class`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/administrative-classes` | 行政班列表 (`list_admin_classes`) | `academic.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/administrative-classes/{class_id}` | 更新行政班 (`update_admin_class`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/administrative-classes/{class_id}` | 行政班详情 (`get_admin_class`) | `academic.read` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/students` | 创建学生 (`create_student`) | `student.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/students` | 学生列表 (`list_students`) | `student.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/students/{student_id}` | 更新学生 (`update_student`) | `student.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/students/{student_id}` | 学生详情 (`get_student`) | `student.read` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/courses` | 创建课程 (`create_course`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/courses` | 课程列表 (`list_courses`) | `academic.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/courses/{course_id}` | 更新课程 (`update_course`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/courses/{course_id}` | 课程详情 (`get_course`) | `academic.read` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/teaching-classes` | 创建教学班 (`create_teaching_class`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/teaching-classes` | 教学班列表 (`list_teaching_classes`) | `academic.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/teaching-classes/{tc_id}` | 更新教学班 (`update_teaching_class`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/teaching-classes/{tc_id}` | 教学班详情 (`get_teaching_class`) | `academic.read` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/teaching-classes/{tc_id}/students` | 读取教学班名单 (`list_roster`) | `student.read` | 按资源及学期范围 |
| `PUT` | `/api/v1/academic/teaching-classes/{tc_id}/students` | 整体替换教学班名单 (`replace_roster`) | `student.manage` | 按资源及学期范围 |
| `POST` | `/api/v1/academic/course-schedules` | 创建课表条目 (`create_schedule`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/course-schedules` | 课表条目列表 (`list_schedules`) | `academic.read` | 按资源及学期范围 |
| `PATCH` | `/api/v1/academic/course-schedules/{schedule_id}` | 更新课表条目 (`update_schedule`) | `academic.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/course-schedules/{schedule_id}` | 课表条目详情 (`get_schedule`) | `academic.read` | 按资源及学期范围 |
| `DELETE` | `/api/v1/academic/course-schedules/{schedule_id}` | 删除课表条目 (`delete_schedule`) | `academic.manage` | 按资源及学期范围 |
| `PUT` | `/api/v1/academic/volunteer-qualifications` | 设置志愿者学期资格 (`upsert_volunteer_qualification`) | `volunteer.manage` | 按资源及学期范围 |
| `GET` | `/api/v1/academic/volunteer-qualifications` | 志愿者学期资格列表 (`list_volunteer_qualifications`) | `volunteer.read` | 按资源及学期范围 |
| `GET` | `/api/v1/import-templates/{target}` | 读取导入模板 (`get_import_template`) | `目标 manage（roster→student.manage；timetable→academic.manage；volunteer→volunteer.manage）` | 按目标资源 |
| `POST` | `/api/v1/imports` | 上传并预览导入 (`create_import`) | `import.execute ＋目标 manage` | 按目标资源与学期／教学班 |
| `GET` | `/api/v1/imports/{batch_id}` | 读取导入批次 (`get_import`) | `import.execute ＋目标 manage` | 本次导入批次可见范围 |
| `POST` | `/api/v1/imports/{batch_id}/confirm` | 确认原子导入 (`confirm_import`) | `import.execute ＋目标 manage` | 批次作用域及引用重校验 |
| `GET` | `/api/v1/imports/{batch_id}/errors` | 读取导入错误 (`import_errors`) | `import.execute ＋目标 manage` | 批次可见范围 |
| `POST` | `/api/v1/inspection-tasks/preview` | 预览任务生成 (`preview_inspection_tasks`) | `inspection.generate` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/inspection-tasks/generate` | 生成查课任务 (`generate_inspection_tasks`) | `inspection.generate` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/me/inspection-tasks` | 本人受派任务 (`list_my_inspection_tasks`) | `inspection.read` | 仅本人受派 |
| `GET` | `/api/v1/inspection-tasks` | 管理／受派任务列表 (`list_inspection_tasks`) | `inspection.read` | 管理全量／志愿者本人受派 |
| `GET` | `/api/v1/inspection-tasks/{task_id}` | 任务详情 (`get_inspection_task`) | `inspection.read` | 任务可见性 |
| `GET` | `/api/v1/inspection-tasks/{task_id}/students` | 任务名单快照 (`get_inspection_task_roster`) | `inspection.roster.read` | 任务可见性＋名单 |
| `POST` | `/api/v1/assignments/auto` | 自动排班 (`auto_assign`) | `assignment.manage` | 指定学期未受派未取消任务 |
| `PUT` | `/api/v1/inspection-tasks/{task_id}/assignment` | 人工分配／改派 (`set_task_assignment`) | `assignment.manage` | 指定任务＋候选资格／冲突 |
| `POST` | `/api/v1/assignment-change-requests` | 申请调班 (`create_change_request`) | `assignment.change_request` | 仅本人当前受派 |
| `GET` | `/api/v1/assignment-change-requests` | 管理调班申请 (`list_change_requests`) | `assignment.change_review` | 管理范围 |
| `GET` | `/api/v1/me/assignment-change-requests` | 本人调班申请 (`list_my_change_requests`) | `assignment.change_request` | 仅本人 |
| `POST` | `/api/v1/assignment-change-requests/{request_id}/review` | 审核调班申请 (`review_change_request`) | `assignment.change_review` | 管理范围 |
| `POST` | `/api/v1/inspection-tasks/{task_id}/cancel` | 取消任务 (`cancel_inspection_task`) | `inspection.cancel` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/inspection-tasks/{task_id}/roster-versions` | 更正名单并建版本 (`create_roster_version`) | `inspection.roster.manage` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/inspection-tasks/{task_id}/roster-versions` | 名单版本历史 (`list_roster_versions`) | `inspection.roster.read` | 任务可见性 |
| `GET` | `/api/v1/submission-deadlines/default` | 默认截止配置 (`get_default_deadline`) | `submission_deadline.read` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/submission-deadlines/days` | 日截止列表 (`list_deadline_days`) | `submission_deadline.read` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/submission-deadlines/days/{inspection_date}` | 日截止详情 (`get_deadline_day`) | `submission_deadline.read` | 服务端按业务资源／角色复核 |
| `PUT` | `/api/v1/submission-deadlines/days/{inspection_date}` | 修改日截止 (`update_deadline_day`) | `submission_deadline.manage` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/submission-deadlines/days/{inspection_date}/versions` | 日截止版本 (`list_deadline_day_versions`) | `submission_deadline.read` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/submission-deadlines/settle` | 结算截止时快照 (`settle_deadlines`) | `submission_deadline.manage` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/inspection-tasks/{task_id}/submissions` | 提交查课结果 (`create_inspection_submission`) | `submission.create` | 仅本人当前受派 |
| `GET` | `/api/v1/me/submissions` | 本人提交历史 (`list_my_submissions`) | `submission.read` | 仅本人 |
| `GET` | `/api/v1/submissions/{submission_id}` | 本人提交详情 (`get_my_submission`) | `submission.read` | 仅本人 |
| `GET` | `/api/v1/management/submissions` | 管理审核提交列表 (`list_management_submissions`) | `submission.review` + 管理角色 | 学期／日期／任务／审核状态筛选、稳定分页 |
| `GET` | `/api/v1/management/submissions/{submission_id}` | 管理审核提交详情 (`get_management_submission`) | `submission.review` + 管理角色 | 任务快照、异常项、照片文件 ID |
| `POST` | `/api/v1/submissions/{submission_id}/review` | 审核提交 (`review_submission`) | `submission.review` | 服务端按业务资源／角色复核 |
| `PATCH` | `/api/v1/inspection-tasks/{task_id}/expected-count` | 调整当前应到人数 (`update_expected_count`) | `attendance.expected_count_adjust` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/files` | 上传材料 (`upload_file`) | `登录＋绑定完成；类别校验` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/files/{file_id}/access` | 获取短时访问链接 (`get_file_access`) | `登录＋父资源可见` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/files/{file_id}/download` | 签名下载材料 (`download_file`) | `有效 HMAC 签名及期限` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/me/attendance` | 本人考勤 (`list_my_attendance`) | `attendance.read` | 仅绑定学生本人 |
| `GET` | `/api/v1/attendance` | 管理考勤列表 (`list_attendance`) | `attendance.read` | 管理范围 |
| `GET` | `/api/v1/attendance/{record_id}` | 考勤详情 (`get_attendance`) | `attendance.read` | 管理范围或本人 |
| `GET` | `/api/v1/attendance/{record_id}/versions` | 考勤认定版本 (`list_attendance_versions`) | `attendance.read` | 管理范围或本人 |
| `POST` | `/api/v1/attendance/{record_id}/corrections` | 人工更正考勤 (`correct_attendance`) | `attendance.correct` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/attendance/{record_id}/objections` | 本人考勤异议 (`create_objection`) | `objection.create` | 仅本人考勤 |
| `GET` | `/api/v1/objections` | 异议列表 (`list_objections`) | `objection.read／objection.initial_review／objection.final_review 任一` | 管理范围或本人 |
| `GET` | `/api/v1/objections/{objection_id}` | 异议详情 (`get_objection`) | `objection.read／objection.initial_review／objection.final_review 任一` | 管理范围或本人 |
| `POST` | `/api/v1/objections/{objection_id}/initial-review` | 异议初核 (`initial_review`) | `objection.initial_review` | 服务端按业务资源／角色复核 |
| `POST` | `/api/v1/objections/{objection_id}/final-review` | 异议终审 (`final_review`) | `objection.final_review；改判另需 attendance.correct` | 服务端按业务资源／角色复核 |
| `GET` | `/api/v1/statistics/attendance` | 考勤聚合统计 (`attendance_statistics`) | `statistics.read` | 管理范围聚合 |
| `GET` | `/api/v1/statistics/incomplete-tasks` | 未完成任务清单 (`incomplete_tasks`) | `statistics.read` | 管理范围 |
| `POST` | `/api/v1/reports/weekly/versions` | 生成周报新版本 (`generate_weekly_version`) | `report.generate` | 管理范围周次 |
| `GET` | `/api/v1/reports/{report_id}/versions` | 周报版本及落后状态 (`list_report_versions`) | `report.read` | 管理范围 |
| `GET` | `/api/v1/report-versions/{version_id}/download` | 下载 Excel／快照 (`download_report_version`) | `report.read` | 管理范围；已发布且未过期 |
| `POST` | `/api/v1/me/password-change` | 本人修改密码 (`change_password`) | 有效密码账号 | 仅本人；旧会话撤销 |
| `GET` | `/api/v1/teacher-accounts` | 教师账号列表 (`list_teachers`) | `account.read`（默认仅超管持有） | 分页、查询、状态筛选 |
| `POST` | `/api/v1/teacher-accounts` | 创建教师账号 (`create_teacher`) | `account.manage` + 超管角色 | 账号与教师角色同事务 |
| `PATCH` | `/api/v1/teacher-accounts/{user_id}` | 修改／停用教师 (`update_teacher`) | `account.manage` + 超管角色 | 版本检查；保留历史 |
| `POST` | `/api/v1/teacher-accounts/{user_id}/password-reset` | 重置教师密码 (`reset_password`) | `account.manage` + 超管角色 | 撤销目标会话；不回显密码 |
| `GET` | `/api/v1/course-schedules/export` | 导出课表 XLSX (`export_course_schedules`) | `course_schedule.export` | 学期及教学班范围；最多 10000 行 |
| `GET` | `/api/v1/inspection-course-occurrences` | 查询可选课次 (`get_course_occurrences`) | `inspection.generate` | 返回全范围修订及 `selection_scope` |
| `POST` | `/api/v1/inspection-tasks/{task_id}/restore` | 恢复已取消任务 (`restore_inspection_task`) | `inspection.generate` | 未开始、无执行事实且快照兼容 |
| `GET` | `/api/v1/reports` | 学院周报主记录 (`list_reports`) | `report.read` | 最新已发布版本及源变化 |
| `GET` | `/api/v1/audit-logs` | 审计列表 (`list_audit_logs`) | `audit.read` | 最多 31 天；分页筛选 |
| `GET` | `/api/v1/audit-logs/{log_id}` | 审计详情 (`get_audit_log`) | `audit.read` | before/after 字段白名单 |

`GET /api/v1/academic/teaching-classes` 另支持 `administrative_class_id` 筛选。生成接口在精确课次模式须原样回传 `selection_scope` 和 `selection_revision`，响应增加 `tasks[].task_id` 及 `assignable_task_ids`，供随后仅对本次选中任务调用自动排班。
