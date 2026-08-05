"""Seed an EMPTY scratch repository with a base revision and a reviewable PR.

Refuses to touch a repository that is not empty: this exists to prepare a
throwaway target, never to modify work someone already has. Everything goes
through the REST API, so no credential is ever written to a git remote or a
config file.

The base revision is correct code; the pull request introduces exactly one
defect, so the review has something real to find and changed-scope enforcement
has something real to distinguish from pre-existing code.

Usage:
  uv run python scripts/seed_scratch_pr.py <owner>/<repo>
"""

from __future__ import annotations

import base64
import sys
from typing import Any

import httpx

API = "https://api.github.com"

CARGO_TOML = """\
[package]
name = "scratch"
version = "0.1.0"
edition = "2021"

[dependencies]
"""

README = """\
# scratch

A throwaway repository used to validate the CodeAtlas review pipeline end to
end. The open pull request deliberately introduces one defect.
"""

BASE_LIB = """\
//! A small request handler used to exercise CodeAtlas end to end.

#[derive(Debug, PartialEq, Eq)]
pub enum Response {
    Ok(String),
    Error(String),
}

/// Handle a wire request of the form `get:<key>`.
///
/// Requests arrive from the network and are untrusted: a malformed request must
/// produce an error response and must never terminate the process.
pub fn handle(request: &str) -> Response {
    let mut parts = request.split(':');
    match parts.next() {
        Some("get") => match parts.next() {
            Some(key) => Response::Ok(key.to_string()),
            None => Response::Error("missing key".to_string()),
        },
        _ => Response::Error("unknown verb".to_string()),
    }
}
"""

PR_LIB = """\
//! A small request handler used to exercise CodeAtlas end to end.

#[derive(Debug, PartialEq, Eq)]
pub enum Response {
    Ok(String),
    Error(String),
}

/// Handle a wire request of the form `get:<key>`.
///
/// Requests arrive from the network and are untrusted: a malformed request must
/// produce an error response and must never terminate the process.
pub fn handle(request: &str) -> Response {
    let mut parts = request.split(':');
    match parts.next() {
        Some("get") => {
            let key = parts.next().unwrap();
            Response::Ok(key.to_string())
        }
        _ => Response::Error("unknown verb".to_string()),
    }
}
"""

BRANCH = "review-me"


def main(slug: str) -> int:
    from codeatlas.vcs.github.client import _headers, token_from_keyring

    owner, repo = slug.split("/", 1)
    client = httpx.Client(timeout=60.0)
    headers = _headers(token_from_keyring())

    info = client.get(f"{API}/repos/{owner}/{repo}", headers=headers)
    if info.status_code != 200:
        print(f"cannot read {slug}: {info.status_code} {info.text[:200]}", file=sys.stderr)
        return 1
    data = info.json()
    if data.get("size", 0) != 0:
        print(
            f"REFUSING: {slug} is not empty (size={data['size']}KB). This script only "
            "prepares a throwaway repository; point it at an empty one.",
            file=sys.stderr,
        )
        return 2
    # NOTE: `permissions` here is the *user's role* on the repository, not the
    # token's granted scopes. A fine-grained PAT with Contents: Read reports
    # push=true and still gets 403 on a write. Probe the capability instead of
    # trusting the role.
    probe = client.put(
        f"{API}/repos/{owner}/{repo}/contents/.codeatlas-write-probe",
        headers=headers,
        json={
            "message": "codeatlas write probe",
            "content": base64.b64encode(b"probe\n").decode("ascii"),
            "branch": data.get("default_branch", "main"),
        },
    )
    if probe.status_code == 403:
        print(
            f"REFUSING: the stored token cannot write to {slug}.\n"
            "  The repository role says push=true, but the fine-grained token's\n"
            "  granted permissions do not include Contents: Read and write.\n\n"
            "  Fix at https://github.com/settings/personal-access-tokens :\n"
            "    - open the CodeAtlas token\n"
            "    - Repository access: include this repository\n"
            "    - Permissions -> Contents: Read and write\n"
            "    - Permissions -> Pull requests: Read and write\n",
            file=sys.stderr,
        )
        return 3
    if probe.status_code not in (200, 201):
        print(f"write probe -> {probe.status_code}: {probe.text[:300]}", file=sys.stderr)
        return 3
    # Clean up the probe file so the seeded history stays tidy.
    client.request(
        "DELETE",
        f"{API}/repos/{owner}/{repo}/contents/.codeatlas-write-probe",
        headers=headers,
        json={
            "message": "remove codeatlas write probe",
            "sha": probe.json()["content"]["sha"],
            "branch": data.get("default_branch", "main"),
        },
    )

    def put_file(path: str, content: str, branch: str, sha: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "message": f"Add {path}" if sha is None else f"Update {path}",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        response = client.put(
            f"{API}/repos/{owner}/{repo}/contents/{path}", headers=headers, json=body
        )
        if response.status_code not in (200, 201):
            raise RuntimeError(f"PUT {path} -> {response.status_code}: {response.text[:300]}")
        print(f"  wrote {path} on {branch}")
        return response.json()  # type: ignore[no-any-return]

    print(f"seeding {slug} (empty, push=yes)")
    put_file("README.md", README, "main")
    put_file("Cargo.toml", CARGO_TOML, "main")
    lib = put_file("src/lib.rs", BASE_LIB, "main")

    main_sha = client.get(f"{API}/repos/{owner}/{repo}/git/ref/heads/main", headers=headers).json()[
        "object"
    ]["sha"]
    branch_response = client.post(
        f"{API}/repos/{owner}/{repo}/git/refs",
        headers=headers,
        json={"ref": f"refs/heads/{BRANCH}", "sha": main_sha},
    )
    if branch_response.status_code not in (200, 201):
        print(f"branch creation -> {branch_response.status_code}: {branch_response.text[:200]}")
    else:
        print(f"  created branch {BRANCH}")

    put_file("src/lib.rs", PR_LIB, BRANCH, sha=lib["content"]["sha"])

    pr = client.post(
        f"{API}/repos/{owner}/{repo}/pulls",
        headers=headers,
        json={
            "title": "Simplify the get arm",
            "head": BRANCH,
            "base": "main",
            "body": "Tidies up the `get` branch of the request handler.",
        },
    )
    if pr.status_code not in (200, 201):
        print(f"PR creation -> {pr.status_code}: {pr.text[:300]}", file=sys.stderr)
        return 4
    number = pr.json()["number"]
    print(f"\nREADY: {slug} pull request #{number}")
    print(f"  {pr.json()['html_url']}")
    print("\nNext (read-only):")
    print(f"  uv run python scripts/validate_github.py {slug} {number}")
    print(f"  uv run codeatlas review-pr {slug} {number}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2 or "/" not in sys.argv[1]:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
