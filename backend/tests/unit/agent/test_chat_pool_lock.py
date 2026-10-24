from importlib import import_module, util
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def module():
    assert util.find_spec("app.modules.agent.chat_pool") is not None, (
        "Chat pool coordination is missing"
    )
    return import_module("app.modules.agent.chat_pool")


def test_sqlite_local_guard_is_not_reentrant_and_releases_after_error():
    engine = create_engine("sqlite://")
    with Session(engine) as db:
        guard = module().capacity_guard
        with pytest.raises(RuntimeError), guard(db, "dev", "management") as first:
            assert first is not None
            with guard(db, "dev", "management") as second:
                assert second is None
            raise RuntimeError("synthetic failure")
        with guard(db, "dev", "management") as third:
            assert third is not None
    engine.dispose()


class Connection:
    def __init__(self, *, acquired=1, release_error=False):
        self.calls, self.acquired, self.release_error = [], acquired, release_error
        self.invalidated = False

    def scalar(self, sql, params):
        self.calls.append((str(sql), params))
        if "GET_LOCK" in str(sql):
            return self.acquired
        if self.release_error:
            raise RuntimeError("synthetic private DB detail")
        return 1

    def invalidate(self):
        self.invalidated = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.calls.append(("CLOSE", None))


def mysql_db(connection):
    engine = SimpleNamespace(
        dialect=SimpleNamespace(name="mysql"),
        url=SimpleNamespace(database="campus_test"),
        connect=lambda: connection,
    )
    return SimpleNamespace(get_bind=lambda: engine)


def test_mysql_uses_same_dedicated_connection_and_bounded_named_lock():
    connection = Connection()
    with module().capacity_guard(mysql_db(connection), "dev", "management") as guard:
        assert guard is not None and guard.connection is connection
        assert len(connection.calls) == 1
    assert "GET_LOCK" in connection.calls[0][0]
    assert "RELEASE_LOCK" in connection.calls[1][0]
    assert connection.calls[0][1] == connection.calls[1][1]
    assert len(connection.calls[0][1]["name"]) <= 64
    assert connection.calls[-1][0] == "CLOSE"


def test_failed_release_invalidates_connection_without_echoing_db_error(caplog):
    connection = Connection(release_error=True)
    with module().capacity_guard(mysql_db(connection), "dev", "management"):
        pass
    assert connection.invalidated
    assert "private DB detail" not in caplog.text


def test_busy_mysql_lock_does_not_admit_or_release_another_connection_lock():
    connection = Connection(acquired=0)
    with module().capacity_guard(mysql_db(connection), "dev", "management") as guard:
        assert guard is None
    assert len(connection.calls) == 2 and connection.calls[-1][0] == "CLOSE"
