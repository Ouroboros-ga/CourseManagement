# 小程序接口修复交接：学生资料与教工查课

## 学生“我的”

GET `/api/v1/me` 在已绑定学生时新增以下内容（示例为虚构）：

```json
{
  "data": {
    "student_no": "00123456",
    "college_name": "示例学院",
    "app_context": {
      "student": {
        "student_id": "123",
        "student_no": "00123456",
        "name": "张同学",
        "administrative_class_id": "12",
        "administrative_class_name": "计算机2601",
        "college_id": "1",
        "college_name": "示例学院",
        "enrollment_status": "ENROLLED"
      }
    }
  }
}
```

- 这是增量节选；原 `id/display_name/roles/permissions/binding_required/app_context.staff` 等保留。学生页面可直接用 `data.student_no` 与 `data.college_name`，更完整的信息用 `data.app_context.student`。不要用 username 或 display_name 拆解学号。
- 学号和ID是字符串，保留前导零。无绑定时 student及两个顶层字段为null；历史资料不足可能只有班级/学院为null，界面显示待核对，不猜学院。教师原入口继续用 staff，兼具身份时两个摘要可同时存在。
- 显示摘要不等于新增管理权限。登录/绑定后重新GET `/me`，不要只读旧登录缓存或令牌里的信息。

## 教工“考勤”

GET `/api/v1/me/inspection-records?view=teaching&page=1&page_size=20&inspection_date=2026-10-21` 的路径和参数保留。

- 修复卡片对任务来源的关联范围。无本人有效授课关系的任务不再列出，其详情/名单返回404；不得在客户端按课程名称拼入其他教师或管理员记录。一个教学班有21条考勤，不意味着任何教工都应看到21人。
- `starts_at/ends_at` 为明确带时区的ISO时刻，例如 `2026-10-21T10:50:00+00:00` 即北京时间18:50。按ISO时区解析并在Asia/Shanghai显示，不对字符串直接截时分、不无条件再加8小时。没有可靠历史时间时仍为null。
- 卡片新增 `start_period/end_period`，使用正式任务的小节，不由UTC小时推断。`class_name_snapshot` 同期远端补丁一并保留，用于显示该任务教学班。
- 人数、名单、汇总、导出受本人任职范围约束；合班课可能只显示本人学生。教师更正、辅导员责任范围及文件授权不放宽；不需要更改请求认证方式。

本轮仅实现后端及Web，未修改小程序页面。上线版本和验收边界见 [修复记录](../development/STUDENT_ME_STAFF_SCOPE_FIX_20261021.md)。
