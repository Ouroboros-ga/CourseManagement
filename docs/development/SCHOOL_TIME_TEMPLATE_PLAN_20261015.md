# 学校作息模板补开发实施计划

目标：学校维护可复用的节次模板，学院引用为独立作息草稿，模板更新仅提示，不覆盖学院数据。

本次由 GPT 直接实现。真实学院、课程、成员由使用者导入或维护；不整理生产数据、不启用线上业务开关、不执行生产验收及大范围测试。

1. 在 `academic/school_time_models.py` 新增学校模板和不可变版本，`CollegeTimeProfile` 增加可空来源版本外键；新增增量迁移并保留既有记录。
2. 在 `academic/school_time_schemas.py` 复用现有节次校验；`school_time_service.py` 实现超管维护、学院目录、引用和更新提示。模板引用必须同校，学院必须有完整教务维护权限；来源版本不可变。
3. 在 `academic/school_time_router.py` 新增 API，旧作息 API 与发布规则不变。引用只创建草稿，不发布或绑定，不修改历史任务。
4. Web 组件：`SchoolTimeTemplates` 负责超管目录及编辑，`TimeTemplateImport` 负责学院引用及更新提示，`TimePeriodEditor` 只负责节次编辑；既有作息编辑、发布、绑定继续复用。
5. 同步接口索引、契约和 OpenAPI；在 `docs/testing/school-time-templates/` 提供纯虚构数据和以 API 为主的手工流程、预期结果、记录表。只做必要静态检查及构建，不启动自动业务测试。

约束：模板更新新增版本；停用只阻止新引用；不提供删除及自动覆盖；学院采用新版本时新建草稿，再人工发布和绑定。学校模板不包含学期、校历或教务映射。

## 本次交付记录

上述五项代码和资料已补入当前工作区。已完成新 Python 文件定向 Ruff、Python 语法和 ORM 映射检查、OpenAPI 生成、唯一迁移 head 检查、MySQL 离线 DDL 生成、Web 类型检查及生产构建、Git 空白检查。Vite 首次在沙箱内因 EPERM 失败，正常本机权限重试构建通过；构建仍提示既有大文件体积告警。

没有运行 pytest、浏览器交互、业务测试、MySQL 实际迁移或生产数据整理；没有改服务器和业务开关，尚未提交/推送/部署。`docs/testing/school-time-templates/RESULT.md` 保持未执行。以上静态结果不代替流程包中的业务验收。
