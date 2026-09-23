## 备份与恢复演练手册（RUNBOOK · 本地工作文档，不入 git）

适用范围：查课管理系统后端运行交付（P7 · W7d）。覆盖 MySQL 数据库与应用自管存储对象的
备份、恢复与演练流程。目标环境为 `deploy/docker-compose.yml` 定义的 MySQL 8.4（容器
`cm_mysql`，宿主机端口 `13306`，业务库 `course_management`，集成测试库 `course_management_test`，
utf8mb4 / utf8mb4_0900_ai_ci，默认 `caching_sha2_password`）。生产应置于私网并单独管理，
本手册以容器化开发/预发环境示例，命令在生产按实际主机与权限调整。

冻结纪律：所有阈值与期限（备份频率、保留份数、RPO/RTO 目标、材料归档期限）均为**需业务/
学院确认后设定**的占位参数，本文档不臆造校务制度数值；应用侧对应项一律走 `Settings`/env
（见第四节），代码内不硬编码。

---

### 一、备份对象清单

系统状态分两处，必须同时纳入备份，缺其一都无法完整恢复：

1. **MySQL 数据**：业务库 `course_management`（含 `alembic_version` 迁移版本指针、审计
   `audit_log`、append-only 的版本/考勤/异议等事实表）。字符集与排序须与建库一致，否则
   恢复后中文名/快照可能出现乱码或唯一键误判。
2. **应用自管存储对象**：`FILE_LOCAL_STORAGE_DIR`（local 后端，容器内文件/私有卷）或
   对象存储（COS/OSS）中 `file_object` 表所引用的 `object_key` 对象（提交照片、异议证明、
   导入文件、周报快照 JSON 与 Excel）。对象是私有存储、随机键、不可枚举，仅经数据库行引用。

> 一致性要点：数据库与对象存储分离，无法做到单一事务原子备份。恢复后以数据库 `file_object`
> 行为准做对象存在性核对（见 3.4），缺失对象即视为该材料不可下载（应用侧返回 `FILE_EXPIRED`），
> 不影响其余数据可用性。备份窗口内的写差异由 binlog 追平（见第五节，可选）。

---

### 二、执行备份

#### 2.1 数据库逻辑备份（mysqldump）

```bash
# 变量（生产改真实值；示例沿用 docker-compose 口令）
CM_DB=course_management
CM_HOST=127.0.0.1
CM_PORT=13306
CM_USER=cm_app                       # 需具备 SELECT/LOCK TABLES/SHOW VIEW；备份账号建议只读
TS=$(date +%Y%m%d_%H%M%S)
BKDIR=/var/backups/course_management/$TS
mkdir -p "$BKDIR"

# --single-transaction: InnoDB 一致性快照，不锁表（不阻塞在线读写）
# --routines --triggers: 含存储过程/触发器；--set-gtid-purged=OFF 视复制拓扑按需
# --source-data=2: 在 dump 头注释记录 binlog 位点，供第五节按时间点恢复
docker exec cm_mysql sh -c \
  "exec mysqldump -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \
    --single-transaction --quick --routines --triggers \
    --default-character-set=utf8mb4 --source-data=2 --set-gtid-purged=OFF \
    $CM_DB" \
  | gzip > "$BKDIR/${CM_DB}_${TS}.sql.gz"

echo "$TS $CM_DB" >> "$BKDIR/../backup_index.txt"
```

要点：`--single-transaction` 依赖 InnoDB（`my.cnf` 已 `default-storage-engine=InnoDB`）；
`--quick` 逐行取数避免大表内存溢出；导出为 `.sql.gz` 压缩存放。备份口令从容器环境变量取，
不在宿主机命令行明文落盘。

#### 2.2 存储对象备份

local 后端（对象位于宿主机映射卷或 `FILE_LOCAL_STORAGE_DIR`）：

```bash
# 从 backend/.env 读取 FILE_LOCAL_STORAGE_DIR 指向的目录，整目录增量同步归档
rsync -a --delete \
  "$FILE_LOCAL_STORAGE_DIR/" "$BKDIR/storage_objects/"
tar -czf "$BKDIR/storage_objects_${TS}.tar.gz" -C "$BKDIR" storage_objects
```

对象存储（COS/OSS）后端：用云厂商的版本化 / 跨区复制 / 定期快照能力，备份策略与桶生命周期
对齐材料保留期（见第四节），不要与桶默认的通用生命周期规则混用导致提前删除归档期内的报表件。

---

### 三、恢复（含演练）

恢复演练应**定期在隔离环境执行**（建议频率见第八节占位），验证备份真实可用，而非"备了就完"。

#### 3.1 准备目标库

演练时恢复到**一次性新库**（如 `course_management_restore_drill`），切勿直接覆盖生产：

```bash
docker exec cm_mysql sh -c \
  "exec mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_ROOT_USER_NAME\" -p\"\$MYSQL_ROOT_PASSWORD\" \
   -e \"CREATE DATABASE course_management_restore_drill \
        CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
        GRANT ALL ON course_management_restore_drill.* TO 'cm_app'@'%';\""

# 导入 dump（把 charset/collation 参数保持与建库一致）
gunzip -c "$BKDIR/${CM_DB}_${TS}.sql.gz" | docker exec -i cm_mysql sh -c \
  "exec mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" \
    --default-character-set=utf8mb4 course_management_restore_drill"
```

#### 3.2 恢复存储对象

local 后端解回到临时目录，恢复测试时把 `FILE_LOCAL_STORAGE_DIR` 指向该目录：

```bash
tar -xzf "$BKDIR/storage_objects_${TS}.tar.gz" -C "$BKDIR"
# 演练指向恢复出来的对象目录
export FILE_LOCAL_STORAGE_DIR="$BKDIR/storage_objects"
```

#### 3.3 迁移版本对账

dump 内已含 `alembic_version`，恢复后应与当前代码 head 一致。做一次 `--sql` 干跑或对比确认
无待应用迁移（防"备份的是旧 schema、代码却是新 schema"）：

```bash
cd backend
# 指向恢复出来的库（演练用独立 DATABASE_URL，不改 .env）
DATABASE_URL="mysql+pymysql://cm_app:change_me_app@127.0.0.1:13306/course_management_restore_drill?charset=utf8mb4" \
  uv run alembic current
DATABASE_URL="...同上..." uv run alembic heads        # 期望二者相同
# 若 current 落后于 heads（滚动发布/回滚窗口），按发布流程 upgrade：
DATABASE_URL="...同上..." uv run alembic upgrade head
```

> 说明：生产恢复首选"恢复到与备份时刻代码版本匹配的 schema"，`alembic upgrade head` 仅在
> 需要把旧备份追平到当前版本时执行；不要对生产盲目 upgrade。集成测试用的 `course_management_test`
> 由 fixtures 以 `Base.metadata.create_all` 建表、**不经迁移**，与本手册无关。

#### 3.4 完整性核对清单

恢复后逐项核对，全绿方判定演练成功：

1. `SELECT COUNT(*)` 关键表（`user_account`、`inspection_task`、`attendance_record`、
   `attendance_record_version`、`objection`、`report`、`report_version`、`file_object`、
   `audit_log`、`report_source_revision`）与备份前基线一致（可脚本对比）。
2. `alembic_version` 单行且等于预期 head；`SHOW INDEX` / 约束抽查唯一键存在（如
   `uq_report_version_report_no`、`uq_report_sem_week_scope`）。
3. **孤儿对象核对**：`file_object` 中 `status='READY'` 行的 `object_key` 在恢复出的存储目录
   中均存在；缺失者记录清单，其对应材料按应用侧 `FILE_EXPIRED` 语义处理。
4. 周报可下载核对：抽一份 `status='PUBLISHED'` 的 `report_version`，经下载端点取回
   `excel_file_id`/`snapshot_file_id` 指向的对象，校验字节非空且可打开（Excel 以 `PK` 开头）。
5. 审计链完整：`audit_log` 为 append-only，末条时间戳不早于备份时刻。
6. `/healthz` 返回正常；关键只读接口冒烟通过。

---

### 四、材料保留期与清理的运维配置

清理**不在 API 进程内起定时器**，由部署侧计划任务执行 `deploy/scripts/cleanup_expired_files.py`
（复用 `FileService.purge_expired_files`，逐文件独立事务、可重跑幂等，状态机
`READY→PURGE_PENDING→PURGED`）。

计划任务示例（cron，每日低峰）：

```cron
15 3 * * *  cd /path/to/CourseManagement/backend && \
  .venv/bin/python ../deploy/scripts/cleanup_expired_files.py --batch-size 500 \
  >> /var/log/cm_cleanup.log 2>&1
```

保留期（**均为占位、须业务/学院确认后写进受保护环境配置，不硬编码**）由以下 env 驱动，
落库时固化为每个文件的 `expires_at` 与 `retention_policy_version`，之后不因配置改动而
无审计地缩短旧材料期限：

| env 变量 | 含义 | 默认 |
| --- | --- | --- |
| `FILE_RETENTION_SUBMISSION_PHOTO_DAYS` | 提交照片保留天数 | 见 `Settings` |
| `FILE_RETENTION_OBJECTION_PROOF_DAYS` | 异议证明保留天数 | 见 `Settings` |
| `FILE_RETENTION_REPORT_FILE_DAYS` | 周报快照/Excel 归档天数 | 365 |
| `FILE_RETENTION_IMPORT_FILE_DAYS` | 导入文件保留天数 | 见 `Settings` |
| `FILE_RETENTION_TEMP_DAYS` | 临时件保留天数 | 见 `Settings` |
| `FILE_RETENTION_POLICY_VERSION` | 保留策略版本（固化留痕） | 见 `Settings` |

报表件（`REPORT_FILE`）走**自有归档期限**（默认 365 天），不套用临时件的短周期；未到期的
报表件不会被清理误删，已确到期的按同一状态机清理（`test_report_file_expired_is_purged_but_future_survives`
钉死此不变量）。清理脚本备份前建议先跑一次数据库备份，保证"数据引用与对象删除"的时间先后
与可追溯性。

---

### 五、按时间点恢复（PITR，可选强化）

在 2.1 使用 `--source-data=2` 的前提下，dump 头注释记录了 binlog 文件名与位点。需恢复到
故障前的精确时刻时：

```bash
# 1) 先恢复最近一次全量 dump（见第三节）到目标库
# 2) 从记录的位点起重放 binlog 到目标时刻（--stop-datetime 为 RPO 目标时刻）
docker exec cm_mysql sh -c \
  "exec mysqlbinlog --read-from-remote-server \
     --start-position=<dump记录位点> --stop-datetime='$RECOVERY_TS' \
     <binlog 文件...>" \
  | docker exec -i cm_mysql sh -c \
     "exec mysql -h127.0.0.1 -P3306 -u\"\$MYSQL_USER\" -p\"\$MYSQL_PASSWORD\" $CM_DB"
```

PITR 依赖 binlog 已开启且归档留存；binlog 留存时长、RPO/RTO 目标为需业务确认的占位参数。
存储对象侧无法按时间点精确回放，只能恢复到对象备份的时点，数据库与对象之间存在窗口内
不一致，须以数据引用为准做 3.4 的孤儿核对。

---

### 六、恢复演练记录模板

每次演练留痕，纳入运维台账：

| 项 | 值 |
| --- | --- |
| 演练日期 | ______ |
| 备份时点 / dump 文件 | ______ |
| 备份账号权限核验人 | ______ |
| 恢复到目标库 | course_management_restore_drill |
| 3.4 核对 1–6 结果 | 全绿 / 异常项：______ |
| 实测 RTO（可接受服务恢复用时） | ______（目标值待业务确认） |
| 实测 RPO（丢数据窗口） | ______（目标值待业务确认） |
| 执行人 / 复核人 | ______ |
| 结论与改进项 | ______ |

---

### 七、回滚与应急预案要点

- **发布前**必做数据库全量备份；迁移脚本均可逆（`alembic downgrade`），但生产优先"前滚或
  恢复备份"，避免在承载真实数据的库上 downgrade 丢数据。
- **误删/污染**：立即停写→用最近全量 + PITR 恢复到隔离库→业务确认→切换，切勿在生产原库
  就地试错。
- 凭证（DB 口令、`SECRET_KEY`、微信 AppSecret、对象存储密钥）经受保护环境配置注入，不入库、
  不进 git；轮换后更新备份账号权限与密钥。

---

### 八、参数占位（待学院/业务确认，勿臆造）

- 全量备份频率、备份保留份数与异地留存策略：______
- binlog 开启与留存时长（决定是否支持 PITR 及 RPO 下限）：______
- RPO 目标（可容忍丢数据时间窗）：______
- RTO 目标（可容忍服务不可用时长）：______
- 恢复演练周期（建议不弱于季度一次，最终以业务确认为准）：______

以上任一项未确认前，系统仍可运行，但备份/恢复的合规目标值不预先写死为校务制度。
