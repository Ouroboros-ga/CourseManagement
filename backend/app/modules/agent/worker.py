import logging
import time
from uuid import uuid4

from sqlalchemy.exc import OperationalError

from app.core.exceptions import AppError, ConflictError, ErrorCode
from app.modules.agent.gateway import invoke_tool
from app.modules.agent.task_service import TaskService, visibility_hash

logger = logging.getLogger(__name__)


class Worker:
    def __init__(self, session_factory, connections, *, environment):
        self.session_factory = session_factory
        self.connections, self.environment = connections, environment
        self.worker_id = uuid4().hex

    def _service(self, db):
        return TaskService(db, self.connections, environment=self.environment)

    def run_once(self) -> bool:
        with self.session_factory() as db:
            claim = self._service(db).claim(self.worker_id)
        if claim is None:
            return False
        result, code, retry = None, None, False
        try:
            with self.session_factory() as db:
                service = self._service(db)
                context = service.runs.restore(claim.run_id)
                if visibility_hash(db, context, claim.tool_name) != claim.scope_hash:
                    raise ConflictError(ErrorCode.VERSION_CONFLICT, "可见范围已变化")
                result = invoke_tool(db, context, claim.tool_name, claim.arguments).model_dump(
                    mode="json"
                )
        except AppError as error:
            code = error.code.value
        except OperationalError:
            code, retry = "TEMPORARY_UNAVAILABLE", True
        except Exception:
            # Do not persist exception text or arguments which may include personal data.
            code = "INTERNAL_ERROR"
            logger.error("agent_job_failed", extra={"job_id": claim.job_id, "code": code})
        with self.session_factory() as db:
            self._service(db).finish(claim, result, error_code=code, retry=retry)
        return True


def main():
    import argparse

    from app.core.config import get_settings
    from app.core.database import get_session_factory

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.agent_worker_enabled:
        raise SystemExit("AGENT_WORKER_ENABLED is false")
    worker = Worker(
        get_session_factory(), settings.agent_tool_connections, environment=settings.app_env
    )
    try:
        while True:
            ran = worker.run_once()
            if args.once:
                return
            if not ran:
                time.sleep(0.5)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
