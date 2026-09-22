#!/usr/bin/env python
"""到期材料清理定时脚本（技术方案 16.1 / 16.3；DEVELOPMENT_PLAN 第 65–66 条）。

设计要点：
- 复用 FileService 的 purge_expired_files，而非在应用逻辑里另立一套状态机，也不在
  每个 API 进程内起独立定时器（技术方案 66）——清理由部署侧定时（cron / 任务计划）触发。
- 可重跑、幂等：先把到期 READY 落库为 PURGE_PENDING（持久化清理意图），删底层对象成功
  才置 PURGED 记 purged_at；底层删除失败保留 PURGE_PENDING 待下次运行，绝不把删除失败的
  文件标记为已清理；底层对象已不存在视作清理完成。已 PURGED 者不再入选，重复运行无副作用。
- 逐文件独立提交：单文件失败不回滚其余，也不因个别失败卡死整体作业。
- 仅操作应用自管的存储对象（FILE_LOCAL_STORAGE_DIR / 对象存储），不触碰任何用户目录文件。

运行（PowerShell / Git Bash 同）：
    cd "D:/My project/CourseManagement/backend"
    uv run python ../deploy/scripts/cleanup_expired_files.py --batch-size 500

计划任务示例（cron，每日 03:15）：
    15 3 * * *  cd /path/to/CourseManagement/backend && \
        .venv/bin/python ../deploy/scripts/cleanup_expired_files.py

退出码：0 正常（含"有文件清理失败、留待下次重试"）；1 出现未预期异常。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 脚本位于 deploy/scripts，backend 为其兄弟目录：把 backend 根加入 sys.path 以便 import app。
_BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="清理到期文件底层对象（可重跑）")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="单次处理的最大到期文件数（默认 500）；循环直至无更多可推进对象。",
    )
    parser.add_argument(
        "--max-passes",
        type=int,
        default=1000,
        help="本轮运行最多分批次数，防止因持续失败的对象无限循环（默认 1000）。",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.batch_size <= 0:
        print("--batch-size 必须为正整数", file=sys.stderr)
        return 1

    from app.core.database import get_session_factory
    from app.modules.file.service import FileService

    session = get_session_factory()()  # 自管事务：脚本驱动逐文件提交，不用 session_scope。
    try:
        service = FileService(session)
        total = {"scanned": 0, "marked": 0, "purged": 0, "failed": 0}
        passes = 0
        while passes < args.max_passes:
            passes += 1
            stats = service.purge_expired_files(batch_size=args.batch_size)
            for key in total:
                total[key] += stats[key]
            # 无可清理对象即结束；若一批无任何前进（全为反复失败的历史 PURGE_PENDING），
            # 结束本轮避免空转，剩余留待下次运行重试。
            if stats["scanned"] == 0 or (stats["purged"] + stats["marked"]) == 0:
                break

        summary = {
            "ok": True,
            "passes": passes,
            "scanned": total["scanned"],
            "purged": total["purged"],
            "failed": total["failed"],
        }
        print(json.dumps(summary, ensure_ascii=False))
        if total["failed"] > 0:
            print(
                f"警告：{total['failed']} 个文件底层删除失败，已保留 PURGE_PENDING 待下次重试。",
                file=sys.stderr,
            )
        return 0
    except Exception as exc:  # noqa: BLE001 - 顶层脚本：打印错误并以非零码退出让调度告警
        session.rollback()
        print(json.dumps({"ok": False, "error": repr(exc)}, ensure_ascii=False))
        print(f"清理脚本异常：{exc}", file=sys.stderr)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
