# Upsert a collection_policies row — latest occurred_at wins (ties: payload digest).
from gen_int.python.projection.collection_policy_upsert_projection import collection_policy_upsert_projection
from gen_int.python.projection.collection_policy_upsert_projection import collection_policy_upsert_context
from gen_def.pydantic.events import CollectionPolicySet
from gen_def.sqla.models.pool import CollectionPolicy
from storeutil import lww_wins, naive_utc, payload_digest


def collection_policy_upsert(
    event: CollectionPolicySet,
    context: collection_policy_upsert_context,
) -> None:
    session = context.adapter.session
    digest = payload_digest(event)
    row = session.get(CollectionPolicy, event.collection)
    if row is not None and not lww_wins(event.occurred_at, digest, row.declared_at, row.digest):
        return
    if row is None:
        row = CollectionPolicy(collection=event.collection)
        session.add(row)
    row.min_sites = event.min_sites
    row.verify_max_age_days = event.verify_max_age_days
    row.evictable = bool(event.evictable)
    row.declared_at = naive_utc(event.occurred_at)
    row.digest = digest
    session.flush()
