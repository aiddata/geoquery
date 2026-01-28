"""
Currently just code to create a dummy request for testing purposes.

Placeholder for code to generate request from some user input source (e.g., GeoQuery / API)
"""

from loguru import logger

from gqcore.utils.db.request_generation import Request, RequestItem, insert_request
from gqcore.utils.logs import get_logger

get_logger("create_request")

logger.info("Creating dummy request 1")

request = Request(
    **{
        "source": "script",
        "contact": "sgoodman@aiddata.wm.edu",
        "custom_name": "test1",
        "info": "Nothing1",
        "data": [
            RequestItem(**{"dr_id": 1, "fm_id": 1, "po_id": 1}),
            RequestItem(**{"dr_id": 1, "fm_id": 2, "po_id": 1}),
            RequestItem(**{"dr_id": 1, "fm_id": 3, "po_id": 1}),
            RequestItem(**{"dr_id": 1, "fm_id": 4, "po_id": 1}),
            RequestItem(**{"dr_id": 2, "fm_id": 1, "po_id": 1}),
            RequestItem(**{"dr_id": 2, "fm_id": 2, "po_id": 1}),
            RequestItem(**{"dr_id": 2, "fm_id": 3, "po_id": 1}),
            RequestItem(**{"dr_id": 2, "fm_id": 4, "po_id": 1}),
        ],
    }
)
insert_request(request)

logger.success("Created dummy request 1")

logger.info("Creating dummy request 2")

request = Request(
    **{
        "source": "script",
        "contact": "sgoodman@aiddata.wm.edu",
        "custom_name": "test2",
        "info": "Nothing2",
        "data": [
            RequestItem(**{"dr_id": 1, "fm_id": 11, "po_id": 1}),
            RequestItem(**{"dr_id": 1, "fm_id": 12, "po_id": 1}),
        ],
    }
)
insert_request(request)

logger.success("Created dummy request 2")


from gqcore.utils.db.conn import get_conn

with get_conn() as conn:
    with conn.cursor() as cur:
        cur.execute("""UPDATE extract_tasks SET status = 0 WHERE id = 21 """)
