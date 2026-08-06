"""The graph cache key must be a complete description of what produced a graph.

A graph is a deterministic function of (revision, extractor toolchain, our own
normalization code) — ADR-0007. Reusing a cached graph is therefore sound only
when the key covers all three. A key that omits one of them serves a stale graph
while reporting a fresh hash, which is the one failure mode a cache must not
have: silently changing results.
"""

from __future__ import annotations

from codeatlas.pipeline.graph_cache import fingerprint_from

CARGO = "cargo 1.89.0 (c24e10642 2025-06-23)"
RA = "rust-analyzer 1.89.0 (29483883e 2025-08-04)"


def test_the_same_toolchain_always_produces_the_same_fingerprint() -> None:
    first = fingerprint_from({"cargo-metadata": CARGO, "rust-analyzer-scip": RA})
    second = fingerprint_from({"rust-analyzer-scip": RA, "cargo-metadata": CARGO})
    assert first == second, "declaration order must not affect the key"
    assert first.startswith("sha256:")


def test_a_new_extractor_version_is_a_different_fingerprint() -> None:
    old = fingerprint_from({"cargo-metadata": CARGO, "rust-analyzer-scip": RA})
    new = fingerprint_from({"cargo-metadata": CARGO, "rust-analyzer-scip": RA + "-nightly"})
    assert old != new, "an upgraded extractor can produce a different graph"


def test_dropping_an_extractor_is_a_different_fingerprint() -> None:
    both = fingerprint_from({"cargo-metadata": CARGO, "rust-analyzer-scip": RA})
    one = fingerprint_from({"cargo-metadata": CARGO})
    assert both != one


def test_our_own_normalization_version_participates() -> None:
    """The graph is as much our code's output as the extractors'."""
    from codeatlas.pipeline.graph_cache import GRAPH_PIPELINE_VERSION

    base = fingerprint_from({"cargo-metadata": CARGO})
    bumped = fingerprint_from({"cargo-metadata": CARGO}, pipeline_version="99.0.0")
    assert base != bumped
    assert GRAPH_PIPELINE_VERSION, "the normalization version must be declared, not implied"
