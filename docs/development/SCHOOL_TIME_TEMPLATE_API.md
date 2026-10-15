# 学校作息模板：产品边界与 API

## 产品行为

超管维护学校模板，每个节次包含 `period_no / slot_id / name / start_time / end_time`。`slot_id` 是节次身份，调整时间或名称时应保持不变；新增节次才使用新标识。时间为学校本地钟表时间（Asia/Shanghai），分钟精度，不含时区、不跨午夜、不重叠，最多 60 节。未传 `slot_id` 时兼容生成 `period-N`；名称不能为空。

创建模板即形成第 1 个可引用版本。每次修改保存新增不可变版本；模板停用不删除版本、不改变学院已有数据。没有删除接口。恢复后可再次引用。

学院引用指定版本时创建独立 `DRAFT` 作息方案，保留 `source_template_version_id`。学院可使用旧方案编辑接口自行修改；来源只表示最初复制依据，不表示学校仍控制学院草稿。模板不携带学期、校历、教务映射；引用时选择目标学期、生效日期和草稿名称。

新草稿继续通过既有方案预览和发布流程生效，再由教学班绑定使用；未绑定的教学班仍采用学院默认作息。引用不会自动发布、绑定、取代学院默认配置或影响正式课次。发布后的实际时间解析、已有任务历史快照、未来任务影响处置均复用现有实现。

模板升级或停用时，学院更新提示接口按“来源版本与当前版本”计算提示。没有消息已读、确认或自动采用状态；即使管理员编辑过学院草稿，提示仍不覆盖任何字段。想采用新版时新建草稿，调整、发布和明确绑定；旧方案及来源保留。已归档学院方案不再列入提示。

Web 入口：超管“学院与组织配置 → 学院与授权 → 学校作息模板”；学院“学院作息与校历 → 教学班可选作息方案 → 引用学校作息模板”。无需新增小程序调用或页面。

## 新增接口

下表均以前缀 `/api/v1` 调用；成功统一 `{data, requestId}`，ID 为字符串。旧 API 的请求字段和行为不变，方案返回增加可空来源字段，旧方案值为 null。

| 方法 | 路径 | 授权 / 用途 |
| --- | --- | --- |
| GET | `/schools/{school_id}/time-templates` | 超管：目录，含最新不可变版本 `latest` |
| POST | `/schools/{school_id}/time-templates` | 超管：创建模板及第 1 版 |
| PATCH | `/schools/{school_id}/time-templates/{template_id}` | 超管：新增版本，不改旧版本 |
| GET | `/schools/{school_id}/time-templates/{template_id}/versions` | 超管：历史版本，按版本倒序 |
| POST | `/schools/{school_id}/time-templates/{template_id}/status` | 超管：停用/恢复 |
| GET | `/colleges/{college_id}/time-templates` | 本院 `academic.read`：同校目录（含停用模板） |
| POST | `/colleges/{college_id}/academic/semesters/{semester_id}/time-versions/profiles/from-template` | 本院 `academic.manage`：同校有效模板的指定版本复制为独立草稿 |
| GET | `/colleges/{college_id}/academic/semesters/{semester_id}/time-template-updates` | 本院 `academic.read`：当前学期未归档方案的升级/停用提示 |

所有新增接口依赖 `CAMPUS_CONFIGURATION_ENABLED`。引用写入另外沿用既有作息路由的三项启用条件：`CAMPUS_ACADEMIC_SCOPED_ENABLED`、`CAMPUS_BUSINESS_SCOPED_ENABLED`、`CAMPUS_SCHEDULING_ENABLED`。学校模板维护、学院目录和提示不依赖排班开启。此次不调整任何线上开关。

创建：`{name, periods:[{period_no, slot_id, name, start_time, end_time}]}`。

新增版本：创建字段加 `lock_version`。状态：`{lock_version,status:"ACTIVE"|"INACTIVE"}`。过期版本 409；写入版本、模板状态与审计同事务。

引用：`{template_version_id:"…",name:"学院作息草稿",effective_from:"YYYY-MM-DD"}`。版本 ID 为不可变版本的 `id`，不是模板 ID 或版本号；可从目录的 `latest.id` 取得。有效模板可明确引用旧版本，不会静默替换为最新版。重名冲突返回 409；重复成功请求不另建同名方案，网络状态不明先重新读取方案列表。

引用响应为既有 `CollegeTimeProfile` DTO，含 `status:DRAFT / lock_version / draft_configuration / source_template_version_id`。学院其他归属或越权资源不可读取或修改；跨学校版本返回 404，停用模板引用返回 409，非法时段/标识/生效日期拒绝保存。

提示响应为数组，每项包含 `profile_id/profile_name/template_id/template_name/source_template_version_id/source_version/latest_version/template_status/update_available/message`；没有更新或停用时为空数组，不返回其他学院的引用信息。

## 迁移与交付

增量迁移 `f26a1015e001 → f26a1015f001`：新增 `school_time_template`、`school_time_template_version`，既有 `college_time_profile` 增加可空来源外键；不回填、不清理用户数据。

部署时沿用现有备份/迁移/应用发布流程，给运行账号授予新表所需 SELECT/INSERT/UPDATE 权限。部署实际结果由发布目录CAMPUS_RELEASE.json记录。新增模板事实后不允许通过降级删除；应用回退可保留增量表及可空字段。全库恢复须走已有恢复手册。

本次只做静态校验与 Web 构建，不连接生产、不创建业务测试数据、不运行自动业务验收。人工流程与纯虚构样例见 [测试流程包](../testing/school-time-templates/README.md)。组织学期复制、负责人完整交接不在此次实现范围。
