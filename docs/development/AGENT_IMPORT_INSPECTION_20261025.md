# 智能资料导入：固定整理执行器

日期：2026-10-25。分支：`future/agent-dev`。内部组件候选，未部署。

## 本批交付与边界

已实现可单独终止、限制资源的资料识别子进程，供后续助手导入工作区消费者调用。它复用原 ZIP 安全检查及类型识别，输出来源清单、内容摘要、重复引用和问题提示；不调用模型，不建立预览批次，不保存正式业务资料。

这不是持久导入工作区：原件存储、上传入口、所属学院／来源登录、持久排队、原预览自动交接及审批入库仍待接入。现有导入 HTTP 接口、管理端入口及工具目录未改，不能把内部函数测试描述为用户已能在助手上传并自动导入。

## 执行流程

1. 调用方先核验真实用户、当前学院／学期与导入能力，取得授权原件字节；本执行器不接受网址、存储路径、SQL、代码或执行身份。
2. 父进程检查后缀、名称和输入字节预算，生成随机私有临时目录；输入固定写为 `input.bin`，上传名称只作为元数据。
3. 启动固定 Python 模块，清理继承环境变量。Windows直接使用当前环境对应的基础解释器，绕过 uv/venv启动器；`-S`禁止自动site启动，仅显式加入后端及当前受信依赖目录。
4. 子进程在标准输入处等待。Windows先将实际解释器加入 Job Object，再交付启动元数据；解析开始前已具备资源限制。Unix分支先设置rlimit再导入解析组件。
5. 固定工具检查 ZIP 并在内存读取表格；成员不按上传路径解压到磁盘。对每个文件调用原类型识别，保留相对路径、SHA-256、字节数和独立序号。
6. 父进程读取有界JSON，验证协议、来源摘要、成员顺序和重复引用。超时终止并回收实际子进程；正常／异常结束后删除本次临时目录。

清单中的 `member_no` 是本次来源内的序号，不是数据库编号。`duplicate_of` 指向更早且内容摘要／字节数一致的成员，不删除文件、不合并不同目录中的同名资料。类型不确定时 `target=null`，保留待用户选择状态；识别类型不能授予对应导入权限。空成员独立标记问题，不丢弃同包其他正常成员。原考勤表“仅采用首表”的业务提示继续保留。

## 资源及错误约束

沿用当前源码 `importer/limits.py`：ZIP 50 MiB，单表格10 MiB，最多1000表格／5000目录项，展开后总量200 MiB；确认事务仍按原最多100份一组。历史文档中的20表格／10 MiB ZIP预算不作为本批合同。

| 约束 | 当前实现 |
| --- | --- |
| 默认解析等待 | 30秒，可由受信调用方缩短／调整，最多60秒；不是OS启动和磁盘写入全程硬截止 |
| CPU | 子进程45秒CPU预算；真实CPU耗尽测试尚未执行 |
| Windows内存与进程 | Job Object总提交内存／单进程512 MiB，实际解释器1个，关闭Job终止关联进程 |
| Unix内存 | RLIMIT_AS 512 MiB；与Windows提交内存口径不同，需在目标Linux实际验收 |
| 输出 | 固定 `result.json`，最多2 MiB；Unix另设置文件大小限制，禁用core dump |
| 环境与日志 | 不继承数据库、CAM、存储、代理或模型凭据；stdout/stderr不转发，异常只返回固定分类码 |

错误分为 `IMPORT_INSPECTION_INVALID`（输入／ZIP不合法）、`IMPORT_INSPECTION_TIMEOUT`、`IMPORT_INSPECTION_FAILED`（子进程未完成）、`IMPORT_INSPECTION_UNAVAILABLE`（限制／进程或输出协议不可用）。不把原异常、部署路径或文件内容传入错误记录。资源保护安装失败时拒绝执行，不降级成无限制解析。

这是固定解析流程和资源隔离，不是允许执行不可信代码的安全沙箱。上传字节预算也不保证每个合法大包都能在时限内完成；后续持久工作区需要按预算分批整理和保存中间回执。

## 本地验证

新增14项测试包括真实子进程的混合ZIP识别、相对路径和重复内容、未知表头、空文件与正常文件并存、首表提示、非法成员、启动前输入拒绝、真实超时回收和临时目录清理、清理环境、Windows实际内存超限拒绝、Job关闭终止解释器，以及伪造清单／超量展开预算拒绝。原导入识别、ZIP和大包测试另作回归；Linux仅完成静态类型分支检查，不能据此声称Linux运行验收。

最终智能体及原识别／ZIP／大包定向回归共436项通过；本批源码和测试Ruff通过，3个源码文件在Windows及Linux类型分支检查通过。既有依赖弃用告警保留；未进行运行库迁移，候选迁移头仍为 `f26a1025a011`。

复现（`backend`内）：

```powershell
.venv/Scripts/python.exe -m pytest tests/unit/agent/test_import_inspection_process.py tests/unit/test_import_intake.py tests/unit/test_zip_preview.py tests/unit/test_import_large_archive.py -q
.venv/Scripts/python.exe -m mypy --check-untyped-defs app/modules/agent/import_inspection.py app/modules/agent/import_inspection_process.py app/modules/agent/import_process_limits.py
```

机制依据：[Python 3.12 subprocess](https://docs.python.org/3.12/library/subprocess.html)、[Unix资源限制](https://docs.python.org/3.12/library/resource.html)、[Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)。

## 下一步接入

工作区先持久保存授权原件及用户／学院／来源登录，再由固定消费者领取并调用执行器，回写清单和问题卡；明确类型后创建原预览批次，以批次编号进入已有助手资料核对工具与原确认页面。权限、来源变更、幂等和成功组保留仍在持久业务层实现，不塞进解析子进程。

消费者须与Web API分开运行，按父进程加子进程总峰值规划服务内存；不能直接放进原384 MiB API服务并宣称避免整组OOM。当前没有安装消费者或变更内存配置。父进程强制崩溃时残留临时目录的定期清理、目标Linux资源验证和真实大包时限样本也属于接入门禁。
