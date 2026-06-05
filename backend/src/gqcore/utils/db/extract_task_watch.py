from datetime import datetime, timedelta
from typing import Union

from loguru import logger

from .conn import get_conn


@logger.catch(reraise=True)
def free_dangling_tasks(since: Union[datetime, timedelta]) -> int:
    if isinstance(since, timedelta):
        since_timestamp = datetime.utcnow() - since
    elif isinstance(since, datetime):
        since_timestamp = since
    else:
        raise ValueError("since argument must be a datetime or timedelta object.")

    with get_conn() as conn:
        with conn.cursor() as cur:
            free_dangling_tasks_query = """
                UPDATE extract_tasks
                SET status = 0
                WHERE status = 2
                AND update_time < %s
                RETURNING *;
            """

            cur.execute(free_dangling_tasks_query, (since_timestamp,))
            return len(cur.fetchall())
