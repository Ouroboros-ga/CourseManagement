"""Lifecycle writes use current reads with explicit ordered row locks."""


def begin_lifecycle_write(db) -> None:
    db.rollback()
    if db.get_bind().dialect.name == "mysql":
        db.connection(execution_options={"isolation_level": "READ COMMITTED"})
