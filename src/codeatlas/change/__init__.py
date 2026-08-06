"""Comparing two revisions.

Everything here answers "what changed between base and head" from artifacts that
each describe a single revision. The comparisons are pure: they take facts in and
produce a delta, so they are deterministic, testable without a toolchain, and
incapable of inventing a change that neither side supports.
"""
