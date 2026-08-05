"""GitHub client against recorded responses (no network).

Covers the contract we depend on — pinned SHAs, changed paths, the exact review
request body — plus error propagation, so a GitHub outage surfaces as a typed
failure rather than a silent no-op.
"""

from __future__ import annotations

import httpx
import pytest

from codeatlas.publication.payload import ReviewComment, ReviewPayload
from codeatlas.vcs.github.client import GitHubError, GitHubReader, GitHubWriter

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40

PR_JSON = {
    "number": 7,
    "title": "Add eviction bound",
    "body": "Fixes the cache overflow.",
    "base": {"sha": BASE_SHA},
    "head": {"sha": HEAD_SHA},
}
FILES_JSON = [
    {"filename": "kvstore/src/cache.rs"},
    {"filename": "kvstore/src/api.rs"},
]


def _client(handler) -> httpx.Client:  # type: ignore[no-untyped-def]
    return httpx.Client(transport=httpx.MockTransport(handler))


class TestReader:
    def test_pull_request_pins_shas_and_changed_paths(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/files"):
                return httpx.Response(200, json=FILES_JSON)
            return httpx.Response(200, json=PR_JSON)

        reader = GitHubReader("token", client=_client(handler))
        pr = reader.pull_request("o", "r", 7)
        assert pr.base_sha == BASE_SHA
        assert pr.head_sha == HEAD_SHA
        assert pr.changed_paths == ("kvstore/src/api.rs", "kvstore/src/cache.rs")

    def test_sends_auth_and_version_headers(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, json={"resources": {}})

        GitHubReader("secret-token", client=_client(handler)).rate_limit()
        assert seen["authorization"] == "Bearer secret-token"
        assert seen["x-github-api-version"] == "2022-11-28"

    def test_diff_requests_the_diff_media_type(self) -> None:
        seen: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen.update(request.headers)
            return httpx.Response(200, text="diff --git a/x b/x\n")

        diff = GitHubReader("t", client=_client(handler)).diff("o", "r", 7)
        assert seen["accept"] == "application/vnd.github.diff"
        assert diff.startswith("diff --git")

    @pytest.mark.parametrize("status", [401, 403, 404, 422, 500, 503])
    def test_errors_are_typed_not_swallowed(self, status: int) -> None:
        reader = GitHubReader(
            "t", client=_client(lambda request: httpx.Response(status, text="nope"))
        )
        with pytest.raises(GitHubError) as exc:
            reader.pull_request("o", "r", 7)
        assert exc.value.status == status

    def test_reader_has_no_write_capability(self) -> None:
        """Read and write are separate types so analysis cannot post by accident."""
        assert not hasattr(GitHubReader("t"), "create_review")


class TestWriter:
    def test_review_body_matches_the_github_contract(self) -> None:
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            captured["path"] = request.url.path
            captured["body"] = json.loads(request.content)
            return httpx.Response(
                200, json={"html_url": "https://github.com/o/r/pull/7#pullrequestreview-9"}
            )

        payload = ReviewPayload(
            owner="o",
            repo="r",
            pr_number=7,
            commit_sha=HEAD_SHA,
            body="## CodeAtlas review",
            comments=[ReviewComment(path="kvstore/src/api.rs", line=28, body="finding")],
        )
        url = GitHubWriter("t", client=_client(handler)).create_review(payload)

        assert url.endswith("#pullrequestreview-9")
        assert captured["path"] == "/repos/o/r/pulls/7/reviews"
        body = captured["body"]
        assert isinstance(body, dict)
        assert body["commit_id"] == HEAD_SHA
        assert body["event"] == "COMMENT", "CodeAtlas never approves or requests changes"
        assert body["comments"] == [
            {"path": "kvstore/src/api.rs", "line": 28, "side": "RIGHT", "body": "finding"}
        ]

    def test_write_failure_raises(self) -> None:
        payload = ReviewPayload(
            owner="o",
            repo="r",
            pr_number=7,
            commit_sha=HEAD_SHA,
            body="b",
            comments=[],
        )
        writer = GitHubWriter(
            "t", client=_client(lambda request: httpx.Response(422, text="unprocessable"))
        )
        with pytest.raises(GitHubError):
            writer.create_review(payload)
