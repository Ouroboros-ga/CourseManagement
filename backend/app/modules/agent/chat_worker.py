"""Fixed chat consumer; read-tool work stays on the existing independent consumer."""

import time

from app.core.config import get_settings
from app.modules.agent.adp_chat import AdpChatClient
from app.modules.agent.adp_client import AdpCallError
from app.modules.agent.conversation_service import ConversationService
from app.modules.agent.schemas import ManagementChatContext


class ChatWorker:
    def __init__(
        self,
        session_factory,
        connections,
        *,
        environment,
        app_key_id,
        limits=None,
        client_factory=AdpChatClient.from_settings,
    ):
        self.session_factory, self.connections = session_factory, connections
        self.environment, self.app_key_id = environment, app_key_id
        self.limits, self.client_factory = limits, client_factory

    def _service(self, db):
        return ConversationService(
            db,
            self.connections,
            environment=self.environment,
            app_key_id=self.app_key_id,
            limits=self.limits,
        )

    def run_once(self):
        try:
            client = self.client_factory()
        except AdpCallError:
            return False
        if client.config.tool_app_key_id != self.app_key_id:
            return False
        with self.session_factory() as db:
            service = self._service(db)
            claim = service.claim_queued()
            changed = service.changed
        if claim is None:
            return changed
        if not claim.can_send:
            return True
        try:
            reply = client.chat(
                claim.user_text,
                conversation_id=claim.remote_conversation_id,
                request_id=claim.remote_request_id,
                user_id=claim.user_ref,
                run_token=claim.run_token,
                business_context=ManagementChatContext(
                    college_id=str(claim.college_id),
                    semester_id=str(claim.semester_id),
                    business_date=claim.business_date,
                ),
            )
        except AdpCallError as error:
            with self.session_factory() as db:
                self._service(db).fail(claim, error.code, ambiguous=error.ambiguous)
        except Exception:
            with self.session_factory() as db:
                self._service(db).fail(claim, "CHAT_UPSTREAM_UNCERTAIN", ambiguous=True)
        else:
            with self.session_factory() as db:
                self._service(db).complete(claim, reply.text)
        return True


def main():
    import argparse

    from app.core.database import get_session_factory

    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if not settings.agent_worker_enabled:
        raise SystemExit("AGENT_WORKER_ENABLED is false")
    try:
        client = AdpChatClient.from_settings(settings)
    except AdpCallError as error:
        raise SystemExit(error.code) from None
    worker = ChatWorker(
        get_session_factory(),
        settings.agent_tool_connections,
        environment=settings.app_env,
        app_key_id=client.config.tool_app_key_id,
    )
    try:
        while True:
            changed = worker.run_once()
            if args.once:
                return
            if not changed:
                time.sleep(0.5)
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
