import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

_TASK = "analytics.tasks.blocks.run_extract_block"


# ignore_result for the same reason as run_extract_task: one result row per
# message, and nothing reads them.
@shared_task(ignore_result=True)
def run_extract_block():
    """Compute one extraction block, then dispatch the next.

    One message in, at most one out (database.md section 2): the chain keeps
    its slot busy without growing the queue. Unlike run_extract_task it ends
    when there is nothing to claim, rather than polling an empty table, and
    when the claim itself raises -- the database is likely unreachable, and
    chaining would retry in a tight loop. In both cases dispatch_block_chains
    restarts chains on its next tick. A block that fails after its claim does
    not end the chain: run_block holds its lease for another lease period and
    returns, so the chain moves on to other blocks. See analytics/blocks.py.
    """
    if not settings.EXTRACT_BLOCKS_ENABLED:
        return None

    from analytics.blocks import run_block

    result = run_block()
    if result is not None:
        run_extract_block.delay()
    return result


@shared_task
def dispatch_block_chains():
    """Top up block chains to fill idle slots on the blocks queue.

    Also the recovery trigger for block leases (database.md section 8): an
    expired lease only makes a block claimable, and it is a chain started
    here that claims it. Syncs the progress pairs first, so a newly ingested
    resource or processing option is picked up without the builder.
    """
    if not settings.EXTRACT_BLOCKS_ENABLED:
        return {"dispatched": 0, "enabled": False}

    from analytics.management.commands.build_extract_tasks import sync_progress_pairs
    from analytics.tasks.maintenance import _idle_slots

    sync_progress_pairs()
    workers, total_slots, in_flight = _idle_slots(_TASK)
    to_dispatch = max(0, total_slots - in_flight)
    logger.info(
        "Extract blocks: %d workers, %d total slots, %d in flight, dispatching %d",
        len(workers), total_slots, in_flight, to_dispatch,
    )
    for _ in range(to_dispatch):
        run_extract_block.delay()
    return {"dispatched": to_dispatch, "total_slots": total_slots, "in_flight": in_flight}
