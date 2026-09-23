## 压测与运行验收手册（RUNBOOK · 本地工作文档，不入 git）

适用范围：查课管理系统后端 P7 运行交付（W7d）。给出负载测试方法、可配置的规模/并发护栏、
以及"真实 MySQL 并发 + 双端"验收清单。**所有与学院真实规模相关的数字均为占位，须业务/
学院确认后设定，本文档不臆造**（依据 DEVELOPMENT_PLAN 第 70 条：P7 前用实际学生数、任务数、
峰值同时提交数确定压测目标）。

关联依据：docs/DEVELOPMENT_PLAN.md 第 35 条 P7 验收；docs/P7_REPORT_PLAN.md 第四、五节；
docs/PERMISSIONS.md §2 / §5 / §6.2；技术方案 §17 统计口径、§18 周报、§9.4 源修订、§16.3 材料保留。

---

### 一、规模参数：从何处取值（先定基线，勿拍脑袋）

压测前须由学院/业务提供并填入下表；未确认前不得写死为校务制度进代码：

| 参数 | 含义 | 来源 | 取值 |
| --- | --- | --- | --- |
| `N_STU` | 在册学生总数 | 教务 | ______ |
| `N_TASK_WK` | 单周查课任务峰值数 | 教务/运营 | ______ |
| `N_VOL` | 峰值在岗志愿者数 | 运营 | ______ |
| `Q_SUBMIT_PEAK` | 峰值同时提交并发数 | 业务 | ______ |
| `PEAK_WINDOW` | 峰值时间窗（如截止前 N 分钟） | 业务 | ______ |
| `R_STU_PER_TASK` | 单任务平均应到人数 | 教务 | ______ |

上述取值确定后，才设定第二节的护栏阈值与第三节的目标吞吐/延迟判据。

---

### 二、可配置的规模与并发护栏（冻结纪律：全部走 env）

应用侧内置的"有界同步执行"护栏，压测目标应与之对齐：

| env 变量 | 含义 | 默认 | 压测关注点 |
| --- | --- | --- | --- |
| `REPORT_GENERATE_MAX_TASKS` | 单次周报生成允许聚合的最大任务数，超限在写产物前拒绝（422） | 5000 | 是否覆盖 `N_TASK_WK` 峰值周 |
| `REPORT_GENERATE_TAKEOVER_STALE_SECONDS` | GENERATING 记录可被带 token 接管的陈旧阈值 | 600 | 生成耗时上限须小于它，避免误接管 |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` | 每进程连接池基线/弹性上限 | 5 / 10 | 与并发进程数×峰值请求共同决定 MySQL `max_connections`(=200) 余量 |
| `DB_POOL_TIMEOUT` / `DB_POOL_RECYCLE` | 取连接等待超时 / 空闲回收（适配 wait_timeout） | 30 / 1800 | 高并发下连接等待是否超时 |
| `OBJECTION_WINDOW_DAYS` | 学生对某条考勤可提异议的窗口天数（0=不限） | 7 | 影响异议峰值分布 |
| `OBJECTION_MAX_FILES` | 单次异议附件上限 | 5 | 影响上传峰值 |
| `FILE_MAX_BYTES` / `FILE_MAX_IMAGE_PIXELS` | 单文件大小/像素上限 | 10MB / 4000万 | 影响提交侧 IO 峰值 |
| `FILE_MAX_FILES_PER_SUBMISSION` | 单次提交附件数上限 | 5 | 影响提交事务体量 |

> 周报生成刻意**不引入 worker/队列/Redis/MQ/集群**（技术方案 §66、DEVELOPMENT_PLAN 第 66 条），
> 为受限同步执行；因此"规模超限写入前拒绝"是主保护，压测须验证拒绝路径干净（无悬挂 GENERATING、
> 版本号不被失败尝试占用）。

---

### 三、压测目标判据（阈值待业务确认，先列方法与测量点）

对每类关键场景给出：测量指标、判据形态、目标值占位。工具建议 locust / k6 / wrk，接真实
MySQL（禁 SQLite），并预留隔离压测库。

1. **志愿者提交（写路径，含锁）**
   - 指标：P50/P95/P99 延迟、成功率、事务等待、锁等待与死锁计数、每分钟提交数。
   - 判据：峰值 `Q_SUBMIT_PEAK` 并发下成功率 ≥ 目标、P99 ≤ 目标延迟、无异常死锁堆积
     （死锁应被应用重试语义或客户端串行化吸收）。
   - 目标值：成功率 ______，P99 ______ ms，持续时长 ______ min。

2. **审核生成考勤（写路径，行锁 + 版本）**
   - 指标：同 `N_TASK_WK` 规模下审核吞吐、考勤版本追加写入延迟、与提交的相互阻塞度。
   - 目标值：______

3. **统计只读（GET /statistics/attendance、incomplete-tasks）**
   - 指标：不同 `N_STU×N_TASK_WK` 规模下查询时延、是否触发"先过滤再聚合"的大扫描、慢查询日志
     （`long_query_time=1`）命中数。
   - 判据：无 N+1（校验 SQL 条数恒定）；大范围内仍走索引；分母≤0 维度返回 `null` 而非 0/100%。
   - 目标值：P95 ______ ms，慢查询占比 ______。

4. **周报同步生成（POST /reports/weekly/versions）**
   - 指标：单周生成端到端耗时（三阶段：锁分配版本 / 一致性读快照 / 事务外产 JSON+Excel / 发布）、
     内存峰值、Excel 生成用时；并发多次生成的版本唯一性。
   - 判据：耗时 < `REPORT_GENERATE_TAKEOVER_STALE_SECONDS`；规模超限即时 422 且不产出孤儿文件、
     不留悬挂 GENERATING；并发唯一发布无重复 `version_no`。
   - 目标值：单周生成 P95 ______ s，可接受并发 ______。

5. **下载（GET /report-versions/{id}/download、/files/{id}/download）**
   - 指标：签名链接申请时延、直连下载吞吐（大 Excel）。
   - 目标值：______

连接池与 MySQL 容量核对：`进程数 × (DB_POOL_SIZE + 峰值用到 DB_MAX_OVERFLOW)` 之和应 < MySQL
`max_connections`（当前 `my.cnf`=200）并留余量给运维/备份会话；压测中监控
`Threads_connected` / `Threads_running` / 锁等待。

---

### 四、压测执行步骤（隔离环境）

1. 专用压测库（勿用开发/生产/测试库）：
   ```bash
   docker exec cm_mysql sh -c \
     'mysql -h127.0.0.1 -P3306 -u"$MYSQL_ROOT_USER_NAME" -p"$MYSQL_ROOT_PASSWORD" \
      -e "CREATE DATABASE course_management_load CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"'
   cd backend
   DATABASE_URL="mysql+pymysql://cm_app:change_me_app@127.0.0.1:13306/course_management_load?charset=utf8mb4" \
     uv run alembic upgrade head
   ```
2. 按 `N_STU/N_TASK_WK` 用导入或造数脚本灌入代表性数据（导入走 `importer` 预览→确认原子）。
3. 以第一节护栏 env 起多进程应用（或反向代理后端），对第三节场景加压到 `PEAK_WINDOW` 时长。
4. 采集：应用指标 + MySQL `slow_query_log`（已开）+ `SHOW ENGINE INNODB STATUS` 死锁段 +
   连接数曲线；对照第三节判据逐项判定。
5. 压测结束清理压测库，不复用。

---

### 五、真实 MySQL 并发正确性验收（非压测，属功能红线）

以下不变量已由集成测试在真实 MySQL 上钉死，验收须复核全绿（单进程串行跑，禁并发跑两套
pytest 以免抢占同一 `_test` 库）：

- 同一目标并发授权/撤销：恰好一成功，另一 409 或 422（`test_admin_rbac`）。
- 绑定码并发核销：同一码仅一人成功（行锁串行化，`test_wechat_binding`）。
- 提交与截止结算并发：唯一提交、逾期补交保留未执行考核快照（`inspection`/`attendance`）。
- 周报并发生成：版本号唯一、无悬挂 GENERATING、至少一份 PUBLISHED、接管复用版本号、
  规模超限不占用版本号（`test_report_version`）。
- 审计失败整笔回滚；源修订并发单调无丢失（`report_source_revision`）。

命令：
```bash
cd backend
uv run pytest -q --basetemp="<干净临时目录>" -p no:cacheprovider   # 单进程串行；全量必须一次跑通才算数
```

---

### 六、P7 运行验收清单（对照 DEVELOPMENT_PLAN 第 35 条）

| # | 验收项 | 判据 | 状态 |
| --- | --- | --- | --- |
| 1 | 统计先过滤再聚合 | 无 N+1；聚合先累加分子分母再相除，非班级百分比平均；分母≤0→rate=null 且 `statistics_available=false` | ______ |
| 2 | 「当前未完成」与「截止时未完成」分别命名输出 | 两轴独立、不混用同名指标；CANCELED 不计入未完成 | ______ |
| 3 | 周报保留版本、最终版本修改时间可见 | `report.latest_version_no` / `latest_updated_at`；版本列表含每版 `generated_at`、不可覆盖递增 | ______ |
| 4 | 落后源 / 公式 / 模板 陈旧提示 | `behind_source`、`rule_outdated`、`template_outdated` 计算正确 | ______ |
| 5 | 照片/证明/报表分别配置保留期限 | 各自 env；落库固化 `expires_at`+`retention_policy_version`；报表自有归档期不被清理误删 | ______ |
| 6 | 同步生成有规模/并发限制 | `REPORT_GENERATE_MAX_TASKS` 超限写前 422；并发唯一发布；接管陈旧 GENERATING | ______ |
| 7 | 下载鉴权与明细可见性 | 生成需 `report.generate`（管理范围），读取需 `report.read`；`statistics.read` 不隐式获得 `report.read`；已清理/到期 `FILE_EXPIRED` | ______ |
| 8 | 清理脚本部署可跑 | `cleanup_expired_files.py` 退出码 0、逐文件独立事务、可重跑幂等（`test_cleanup_script` 端到端） | ______ |
| 9 | 恢复演练 | RUNBOOK_BACKUP_RESTORE 第三节 3.4 核对 1–6 全绿 | ______ |
| 10 | 真实 MySQL 并发与双端验收 | 第五节不变量全绿；Web 管理端 + 微信小程序端到端（前端波次另验收） | ______ |

双端（管理后台 + 小程序）为前端波次交付项，本手册仅登记后端契约就绪度；前端接入后补端到端
签字。

---

### 七、待确认项汇总（未给数字不臆造）

- 第一节全部规模基线取值：______
- 第三节各场景吞吐/延迟/成功率目标阈值：______
- 备份/恢复 RPO、RTO、演练周期（见 RUNBOOK_BACKUP_RESTORE 第八节）：______
- Excel 真实模板样例（技术方案 §19 非目标已声明 V1.0 先以"后端写死数值 + 通用工作簿"交付，
  模板往返兼容待样例到位后验收）：______

以上任一确认到位后，回填对应章节并将护栏 env 写入受保护环境配置；在此之前不得将任何规模
数值固化为代码默认或校务制度。
