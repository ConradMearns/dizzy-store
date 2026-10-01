# A collection's policy, or the defaults when undeclared.
from gen_int.python.query.get_collection_policy import get_collection_policy_query, get_collection_policy_context
from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput, GetCollectionPolicyOutput
from gen_def.sqla.models.pool import CollectionPolicy
from storeutil import iso, policy_for


def get_collection_policy(input: GetCollectionPolicyInput, context: get_collection_policy_context) -> GetCollectionPolicyOutput:
    session = context.adapter.session
    p = policy_for(session, input.collection)
    row = session.get(CollectionPolicy, input.collection)
    return GetCollectionPolicyOutput(
        collection=input.collection, min_sites=p.min_sites,
        verify_max_age_days=p.verify_max_age_days, evictable=p.evictable,
        declared=p.declared, declared_at=iso(row.declared_at) if row is not None else "")
