"""Pure claim rules shared by direct RADAR starts and pipeline activations."""

from types import SimpleNamespace

from off_key_core.db.pipeline_claims import claim_owners, first_overlap


def test_first_overlap_returns_the_first_matching_filter_pair():
    assert first_overlap(["a/b", "c/+"], ["x/y", "c/d"]) == ("c/+", "c/d")
    assert first_overlap(["a/#"], ["a/b/c"]) == ("a/#", "a/b/c")
    assert first_overlap(["a/b"], ["a/c", "b/#"]) is None
    assert first_overlap([], ["a/b"]) is None


def test_claim_owners_count_targets_once_and_release_replaced_services():
    active = [SimpleNamespace(id=name) for name in ("old", "steady", "replaced")]
    pending = [SimpleNamespace(service_id="new", predecessor_service_id="old")]

    # A replacement holds one slot: the target counts, its predecessor does not.
    assert claim_owners(active, pending) == {"steady", "replaced", "new"}
    assert claim_owners(active, pending, released=["replaced"]) == {"steady", "new"}
    assert claim_owners(active, []) == {"old", "steady", "replaced"}
