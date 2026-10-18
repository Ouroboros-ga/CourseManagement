# 2026-10-18 导入、人员关系与报表发布记录

应用源码：`bed04b8ca50a7322bcd5add7641c03e4c3f302ca`，已合入并推送 `dev-main`。发布时间：2026-10-18 17:35:40（北京时间）。本记录后续提交仅含文档，不改变应用源码。

## 发布范围

- 文件夹、ZIP、多文件上传，逐文件预览、失败显式排除与选定集合确认；学校模式网格小节解析修正。
- 导入时通过工号或无歧义姓名关联既有人员档案，存量关联预览/确认及 Web 入口，跨院授课关系按课程负责学院管理。
- 报表按冻结学院/行政班 ID 分组与下钻，负责人按关系有效期读取；保留历史快照及旧数据兼容。
- 保留远端 `/me` 教工学院名称增量；修复既有失效 favicon 引用，复用校徽构建资源。

未执行生产人员回填、权限 seed、迁移、功能开关修改；未实现混合资料依赖草稿的统一导入工作台。

## 验证边界

- 功能提交阶段后端 66 项、前端 7 项定向测试通过；关键文件定向类型检查与新增行 lint 见[补齐记录](PERSON_RELATION_COMPLETION_20261018.md)。非全仓 lint 通过结论。
- 合并远端后 16 项身份/导入关联/报表回归通过；Web 类型检查与生产构建通过。
- 服务器独立候选进程 ready 和 OpenAPI 检查通过；切换后内网、公网 ready、Web 入口与引用本地资源哈希通过。
- 新人员关联预览/确认接口匿名请求均 401；生产只读事务核对迁移头 `f26a1018s006`；有效业务隔离为 true、组织排班为 false。配置文件哈希与切换前一致。
- 未重复全量 MySQL 并发演练，未上传真实教务数据验证写入，未宣称新增页面浏览器全链路或微信真机验收完成。

## 发布与恢复

- 后端：`/opt/course-management/releases/20261018-person-import-bed04b8ca5`。
- Web：`/opt/course-management/admin-web/releases/20261018-person-import-bed04b8ca5`。
- 备份：`/var/backups/course-management/20261018T093529Z.PJDUZ7`，SHA256SUMS 校验通过。
- 上一后端：`/opt/course-management/releases/20261018-me-college-3359f0d321`。
- 上一 Web：`/opt/course-management/admin-web/releases/20261018-staff-f3539a1ced`。
- 恢复应用时原子恢复两处 current 链接、重启 course-management，并检查内外网 ready；本次无结构变更，不需要降级数据库。恢复备份属于数据恢复操作，不能替代应用回退。
- 证据保存在服务器 incoming 对应版本目录的 `DEPLOYED.json`、`ONLINE_VERIFICATION.json`，发布目录的 `RELEASE.json` 及 Web 的 `WEB_RELEASE.json`。

首次切换因资源检查发现既有 favicon 缺失而自动恢复旧指针。修复引用后以新 SHA 重新打包部署；失败候选保留作追溯。

主工作区原有六份未提交文档已备份；README 及未跟踪文件保留，文档导航冲突保留双方内容。未把其他任务文档带入应用发布提交。
