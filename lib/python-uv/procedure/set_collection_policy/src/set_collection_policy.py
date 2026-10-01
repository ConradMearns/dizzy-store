# Declare a collection's policy. Rejects a policy that could never be met.
from gen_int.python.procedure.set_collection_policy_protocol import set_collection_policy_protocol
from gen_int.python.procedure.set_collection_policy_context import set_collection_policy_context
from gen_def.pydantic.commands import SetCollectionPolicy
from gen_def.pydantic.events import CollectionPolicySet
from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput
from storeutil import strictly_after


def set_collection_policy(
    context: set_collection_policy_context,
    command: SetCollectionPolicy,
) -> None:
    if command.min_sites < 1:
        raise ValueError("min_sites must be at least 1")
    if command.verify_max_age_days < 1:
        raise ValueError("verify_max_age_days must be at least 1")
    current = context.query.get_collection_policy(
        GetCollectionPolicyInput(collection=command.collection))
    occurred_at = strictly_after(command.occurred_at, current.declared_at)
    context.emit.collection_policy_set(CollectionPolicySet(
        collection=command.collection, min_sites=command.min_sites,
        verify_max_age_days=command.verify_max_age_days, evictable=command.evictable,
        occurred_at=occurred_at))
