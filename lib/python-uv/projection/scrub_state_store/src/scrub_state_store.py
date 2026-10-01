# Scrub progress per (node, epoch, collection). A pass can span many budgeted runs,
# so freshness is anchored to the pass's START: blobs verified early in a long pass
# are only as fresh as its beginning (stamping the completion time would let a
# day-1 verification count as fresh on day 58).
from gen_int.python.projection.scrub_state_store_projection import scrub_state_store_projection
from gen_int.python.projection.scrub_state_store_projection import scrub_state_store_context
from gen_def.pydantic.events import ScrubCompleted
from gen_def.sqla.models.pool import ScrubState
from storeutil import naive_utc, scrub_id


def scrub_state_store(
    event: ScrubCompleted,
    context: scrub_state_store_context,
) -> None:
    session = context.adapter.session
    key = scrub_id(event.node_id, event.epoch, event.collection)
    row = session.get(ScrubState, key)
    if row is None:
        row = ScrubState(id=key, node_id=event.node_id, epoch=event.epoch,
                         collection=event.collection or "")
        session.add(row)
    started = naive_utc(event.pass_started_at or event.occurred_at)
    if event.pass_complete:
        row.cursor = None
        row.pass_started_at = None
        if row.last_full_pass_at is None or started > row.last_full_pass_at:
            row.last_full_pass_at = started
    else:
        row.cursor = event.cursor
        row.pass_started_at = started
    session.flush()
