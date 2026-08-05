"""Independently validate GitHub access before the pipeline relies on it.

Read-only. This never posts anything: it proves the token works, the scopes are
sufficient, and a pull request can be pinned reproducibly by SHA. Run it once
after storing a token, and again whenever the token is rotated.

Usage:
  uv run python scripts/validate_github.py <owner>/<repo> <pr-number>
"""

from __future__ import annotations

import sys


def main(slug: str, pr_number: int) -> int:
    from codeatlas.vcs.github.client import GitHubError, GitHubReader, token_from_keyring

    if "/" not in slug:
        print(f"expected <owner>/<repo>, got {slug!r}", file=sys.stderr)
        return 2
    owner, repo = slug.split("/", 1)

    checks: list[tuple[str, bool, str]] = []

    try:
        token = token_from_keyring()
    except GitHubError as exc:
        print(f"FAIL  token: {exc}", file=sys.stderr)
        return 1
    checks.append(("token present in Credential Manager", True, f"{len(token)} chars"))

    reader = GitHubReader(token)

    try:
        limits = reader.rate_limit()
        core = limits["resources"]["core"]
        checks.append(
            (
                "authenticated API access",
                core["limit"] >= 5000,
                f"{core['remaining']}/{core['limit']} requests remaining",
            )
        )
    except GitHubError as exc:
        checks.append(("authenticated API access", False, str(exc)))
        _report(checks)
        return 1

    try:
        pr = reader.pull_request(owner, repo, pr_number)
        checks.append(
            (
                "pull request metadata (Pull requests: Read)",
                True,
                f"#{pr.number} {pr.title[:50]!r}",
            )
        )
        checks.append(
            (
                "revisions pinnable",
                len(pr.base_sha) == 40 and len(pr.head_sha) == 40,
                f"base {pr.base_sha[:10]} head {pr.head_sha[:10]}",
            )
        )
        checks.append(
            (
                "changed paths (Contents: Read)",
                bool(pr.changed_paths),
                f"{len(pr.changed_paths)} file(s): {', '.join(pr.changed_paths[:3])}",
            )
        )
    except GitHubError as exc:
        checks.append(("pull request metadata", False, str(exc)))
        _report(checks)
        return 1

    try:
        diff = reader.diff(owner, repo, pr_number)
        from codeatlas.review.scope import parse_added_lines

        added = parse_added_lines(diff)
        total = sum(len(lines) for lines in added.values())
        checks.append(("unified diff", bool(diff.strip()), f"{len(diff)} bytes"))
        checks.append(
            (
                "diff parses into added lines",
                total > 0,
                f"{total} added line(s) across {len(added)} file(s)",
            )
        )
    except GitHubError as exc:
        checks.append(("unified diff", False, str(exc)))

    ok = _report(checks)
    if ok:
        print()
        print("GitHub access validated. Nothing was posted.")
        print(f"Analyze this PR with:  uv run codeatlas review-pr {slug} {pr_number}")
    return 0 if ok else 1


def _report(checks: list[tuple[str, bool, str]]) -> bool:
    print()
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name:<45} {detail}")
    return all(passed for _, passed, _ in checks)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1], int(sys.argv[2])))
