"""Wait until requests are really blocked on a row lock, instead of sleeping and hoping.

The row-lock tests hold a row with one connection, start requests on others, and
need those requests to be waiting on the lock before they assert anything. A
fixed ``time.sleep(1)`` cost a second per test and proved nothing about whether
the requests had got there. This asks Postgres: ``pg_stat_activity`` shows a
backend waiting on a lock (``wait_event_type = 'Lock'``) and ``pg_blocking_pids``
says who it waits for. The second request in a queue waits for the first, not for
the holder, so the blockers are followed transitively back to the holder.
"""

import time

from sqlalchemy import text

POLL_SECONDS = 0.02
TIMEOUT_SECONDS = 15

_WAITING_BEHIND = text("""
    WITH RECURSIVE waiting(pid) AS (
        SELECT pid FROM pg_stat_activity
        WHERE wait_event_type = 'Lock' AND :holder = ANY(pg_blocking_pids(pid))
        UNION
        SELECT a.pid FROM pg_stat_activity a JOIN waiting w ON w.pid = ANY(pg_blocking_pids(a.pid))
        WHERE a.wait_event_type = 'Lock'
    )
    SELECT count(*) FROM waiting
""")


def wait_until_blocked(db, owner, holding, futures: list, *, timeout: float = TIMEOUT_SECONDS) -> None:
    """Return once every request in ``futures`` is waiting, directly or in a queue, on ``owner``'s lock.

    ``owner`` is the connection holding the lock and ``holding`` its open
    transaction. Fails the test, naming what it saw, when a request finishes
    without having waited (the lock is not taken) or when they are not all
    waiting within ``timeout`` seconds. Either way the lock is let go first,
    otherwise the requests would never finish and the test would hang on joining
    its threads instead of failing. Polls from a separate autocommit connection:
    a transaction would keep serving the first ``pg_stat_activity`` it saw.
    """
    holder = owner.execute(text("SELECT pg_backend_pid()")).scalar_one()
    deadline = time.monotonic() + timeout
    waiting = 0
    try:
        with db.owner_engine.connect().execution_options(isolation_level="AUTOCOMMIT") as probe:
            while True:
                assert not any(future.done() for future in futures), (
                    "a request went past a held row lock"
                    f" (backends waiting on it: {waiting} of {len(futures)})"
                )
                waiting = probe.execute(_WAITING_BEHIND, {"holder": holder}).scalar_one()
                if waiting >= len(futures):
                    return
                assert time.monotonic() < deadline, (
                    f"only {waiting} of {len(futures)} requests were waiting on the held row lock"
                    f" after {timeout} s"
                )
                time.sleep(POLL_SECONDS)
    except BaseException:
        holding.rollback()
        raise
