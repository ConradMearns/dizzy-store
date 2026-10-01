"""The implementation matches the feat — the guard the logger's validate_against_feat
gives it, here derived from the feat itself rather than hand-mirrored."""
from dizzy_store.sim import SimCluster
from dizzy_store.wiring import GRAPH, registered, validate_against_feat


def test_every_declared_element_is_wired(tmp_path):
    node = SimCluster(tmp_path).add_node("n")
    validate_against_feat(node.engine)
    wired = registered(node.engine)
    for section in ("procedures", "policies", "projections"):
        assert wired[section] == set(GRAPH.names(section))


def test_every_command_has_a_procedure(tmp_path):
    node = SimCluster(tmp_path).add_node("n")
    routed = {cls for cls in node.engine._procedures}
    assert routed == set(GRAPH.commands.values())


def test_every_query_is_callable(tmp_path):
    node = SimCluster(tmp_path).add_node("n")
    for name in GRAPH.names("queries"):
        assert callable(getattr(node.queries, name)), name


def test_blob_hash_layout_matches_the_logger_cas(tmp_path):
    """Adopting the logger's existing cas/ tree in place relies on this layout."""
    from storeutil import blob_path
    h = "ab" + "cd" + "0" * 60
    assert blob_path("/r", h).as_posix() == f"/r/ab/cd/{h}"
