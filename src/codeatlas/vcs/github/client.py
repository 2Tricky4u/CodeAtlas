"""GitHub REST client (httpx + fine-grained PAT).

Read and write are separated at the type level: `GitHubReader` can only fetch,
and is what the analysis path uses. `GitHubWriter` is the single object able to
post, and the publication gate is the only caller permitted to construct one.

The token is read from Windows Credential Manager at call time and never logged,
stored, or passed into an agent session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from codeatlas.core.logging import get_logger
from codeatlas.publication.payload import ReviewPayload

log = get_logger("codeatlas.github")

API = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"
_TIMEOUT = httpx.Timeout(30.0)


class GitHubError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API {status}: {message[:400]}")
        self.status = status


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    owner: str
    repo: str
    number: int
    base_sha: str
    head_sha: str
    title: str
    body: str
    changed_paths: tuple[str, ...]


def token_from_keyring() -> str:
    import keyring

    token = keyring.get_password("codeatlas/github", "pat")
    if token is None:
        raise GitHubError(
            0,
            "no GitHub token in Windows Credential Manager (codeatlas/github/pat); "
            "see docs/runbooks/setup.md",
        )
    return token


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": _ACCEPT,
        "X-GitHub-Api-Version": _API_VERSION,
        "User-Agent": "codeatlas",
    }


class GitHubReader:
    """Read-only access. Cannot post: there is no method that writes."""

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def _get(self, path: str, accept: str | None = None) -> httpx.Response:
        headers = _headers(self._token)
        if accept:
            headers["Accept"] = accept
        response = self._client.get(f"{API}{path}", headers=headers)
        if response.status_code >= 400:
            raise GitHubError(response.status_code, response.text)
        return response

    def rate_limit(self) -> dict[str, Any]:
        return self._get("/rate_limit").json()  # type: ignore[no-any-return]

    def pull_request(self, owner: str, repo: str, number: int) -> PullRequestRef:
        data = self._get(f"/repos/{owner}/{repo}/pulls/{number}").json()
        files = self._get(f"/repos/{owner}/{repo}/pulls/{number}/files?per_page=100").json()
        return PullRequestRef(
            owner=owner,
            repo=repo,
            number=number,
            base_sha=data["base"]["sha"],
            head_sha=data["head"]["sha"],
            title=data.get("title", ""),
            body=data.get("body") or "",
            changed_paths=tuple(sorted(f["filename"] for f in files)),
        )

    def diff(self, owner: str, repo: str, number: int) -> str:
        return self._get(
            f"/repos/{owner}/{repo}/pulls/{number}", accept="application/vnd.github.diff"
        ).text


class GitHubWriter:
    """Write access. Only the publication gate should hold one of these."""

    def __init__(self, token: str, client: httpx.Client | None = None) -> None:
        self._token = token
        self._client = client or httpx.Client(timeout=_TIMEOUT)

    def create_review(self, payload: ReviewPayload) -> str:
        path = f"/repos/{payload.owner}/{payload.repo}/pulls/{payload.pr_number}/reviews"
        response = self._client.post(
            f"{API}{path}", headers=_headers(self._token), json=payload.to_github()
        )
        if response.status_code >= 400:
            raise GitHubError(response.status_code, response.text)
        data = response.json()
        url = data.get("html_url") or data.get("url") or ""
        log.info(
            "github.review_created",
            repo=f"{payload.owner}/{payload.repo}",
            pr=payload.pr_number,
            comments=len(payload.comments),
        )
        return str(url)
