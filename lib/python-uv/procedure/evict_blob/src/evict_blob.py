# Drop this node's bytes for one blob. Nothing destroys the last copy: refuse (quietly,
# to progress telemetry) unless every guard holds — and PROVE the other copies live
# before deleting anything. A peer's claim in the log is not proof, and neither is a
# matching file size: each peer is asked to re-hash its file and to report its own
# live role and draining state (a peer that is itself leaving does not count).
from datetime import timedelta
from gen_int.python.procedure.evict_blob_protocol import evict_blob_protocol
from gen_int.python.procedure.evict_blob_context import evict_blob_context
from gen_def.pydantic.commands import EvictBlob
from gen_def.pydantic.events import BlobEvicted
from gen_def.pydantic.query.get_blob import GetBlobInput
from gen_def.pydantic.query.get_blob_replicas import GetBlobReplicasInput
from gen_def.pydantic.query.get_collection_policy import GetCollectionPolicyInput
from gen_def.pydantic.query.get_node_profile import GetNodeProfileInput
from gen_def.pydantic.telemetry import PeerHealth, Progress
from storeutil import PeerUnreachable, Policy, blob_path, counts_toward_min_sites, now_utc


def evict_blob(
    context: evict_blob_context,
    command: EvictBlob,
) -> None:
    store, peers = context.env.store, context.env.peers
    h = command.blob_hash
    path = blob_path(store.root, h)                 # refuses anything that is not a sha256

    def refuse(why: str) -> None:
        context.telemetry.progress(Progress(stage="evict_refused", detail=f"{h[:12]}: {why}"))

    me = context.query.get_node_profile(GetNodeProfileInput(node_id=store.node_id))
    blob = context.query.get_blob(GetBlobInput(blob_hash=h))
    if not me.found or not blob.found:
        return refuse("unannounced node or unregistered blob")
    # role closes the double-eviction race (principle 7)
    if me.role == "cold":
        return refuse("a cold device never evicts")
    if command.reason == "pressure" and me.role != "hot":
        return refuse("only a hot node evicts under pressure")
    if command.reason == "drain" and not me.draining:
        return refuse("only a draining node evicts to drain")
    if command.reason not in ("pressure", "drain"):
        return refuse(f"unknown reason {command.reason!r}")

    replicas = context.query.get_blob_replicas(GetBlobReplicasInput(blob_hash=h))
    rows = list(zip(replicas.node_ids, replicas.states, replicas.pinneds, replicas.sites,
                    replicas.roles, replicas.drainings, replicas.verified_ats))
    mine = [r for r in rows if r[0] == store.node_id and r[1] == "present"]
    if not mine:
        return refuse("not held here")
    if mine[0][2]:
        return refuse("pinned")
    policy = context.query.get_collection_policy(
        GetCollectionPolicyInput(collection=blob.collection))
    if not policy.evictable:
        return refuse("collection is not evictable")
    wants = list(me.wants or [])
    if command.reason == "pressure" and ("*" in wants or blob.collection in wants):
        return refuse("this node wants that collection in full")

    # candidates by the LOG: the same definition of "a copy that counts" the queries use
    window = Policy(policy.min_sites, policy.verify_max_age_days)
    now = now_utc()
    candidates = [r for r in rows
                  if r[0] != store.node_id and counts_toward_min_sites(r[1], r[5], r[6], window, now)]
    candidates.sort(key=lambda r: (r[4] != "archive", r[0]))      # archives first: prove the anchor early

    # ... then by PROOF: the peer re-hashes its file, and speaks for itself
    proven_sites: set[str] = set()
    anchor = False
    for node_id, _state, _pinned, site, _role, _draining, _verified in candidates:
        try:
            proof = peers.verify_blob(node_id, h)
        except PeerUnreachable as exc:
            context.telemetry.peer_health(PeerHealth(
                peer_id=node_id, reachable=False, detail=str(exc)))
            continue
        context.telemetry.peer_health(PeerHealth(peer_id=node_id, reachable=True))
        if not proof or not proof.get("held") or proof.get("draining"):
            continue                                # missing, wrong bytes, or itself leaving
        proven_sites.add(site)
        anchor = anchor or proof.get("role") == "archive"
        if len(proven_sites) >= policy.min_sites and anchor:
            break
    if len(proven_sites) < policy.min_sites or not anchor:
        return refuse(f"only {len(proven_sites)} site(s) proven live"
                      f"{'' if anchor else ', no always-on archive among them'}"
                      f" (need {policy.min_sites})")

    path.unlink(missing_ok=True)
    context.emit.blob_evicted(BlobEvicted(
        node_id=store.node_id, epoch=store.epoch, blob_hash=h, reason=command.reason,
        confirmed_sites=len(proven_sites), occurred_at=now_utc()))
