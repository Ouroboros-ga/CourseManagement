# 任务6发布、备份与回滚记录

已发布应用提交：`163030740bf505034bc2f8ed81e078ebd11a3ade`。

已发布目录：`/opt/course-management/releases/20261023-task6-163030740b`；Web目录：`/opt/course-management/admin-web/releases/20261023-task6-163030740b`。实际切换、备份和校验结果见[发布记录](deployment-result.json)。

## 发布门禁

1. 核对远端dev-main仍是73a69fb或最终候选的祖先，使用普通快进推送；不force push。
2. CI运行39921490040四项全部成功；记录历史单测/集成失败清单，不增加基线。
3. 校验发布包SHA256、636个文件校验值，依赖锁与旧版本相同；使用现有venv和systemd。
4. 核验服务环境文件不变、业务库127.0.0.1:13308/course_management、迁移f26a1022e001；发布不迁移、不seed、不清理数据。
5. 短时维护期间停应用，备份数据库和配置，检查压缩包及SHA256SUMS；切换后检查就绪、迁移、所有表行数、配置哈希。
6. 恢复Nginx并按现有流程reload；从公网和浏览器复查。

## 应用回滚

旧后端：`/opt/course-management/releases/20261023-task3-73a69fb6d8`。
旧Web：`/opt/course-management/admin-web/releases/20261023-task3-73a69fb6d8`。

维护人员应先冻结写入并记录当前指针/数据状态，然后把 `/opt/course-management/current` 和 `/opt/course-management/admin-web/current` 通过临时符号链接原子替换指回上述两个旧目录，重启 `course-management`，检查 `/health/ready`、网页和基础API。若修改Nginx，必须先 `nginx -t`，再 `nginx -s reload`。发布脚本故障分支执行相同双指针回退。

**应用回退不等于数据库回退。**本次无结构迁移，不执行Alembic降级，不把备份覆盖回现有库，不删除发布后新增的学生、考勤或任务。若需要数据恢复，须单独确认恢复时间点、恢复到新库核验，并评估备份后新数据的保留方案；禁止直接覆盖业务库。

## 数据范围

本轮页面写入仅“文档验收A”（学院2）及990000xx合成数据。隔离MySQL测试库和QA副本保留，未清理原软件学院两个班或历史。生产环境凭据不入库；服务环境文件哈希仅供一致性检查。
