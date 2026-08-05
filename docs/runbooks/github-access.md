# Giving CodeAtlas GitHub access

This is the only setup step that needs a human. It takes about five minutes and
grants **read-only** access; posting a review is a separate, explicitly approved
action that you trigger by hand.

## 1. Create a fine-grained personal access token

Go to <https://github.com/settings/personal-access-tokens/new>.

| Field | Value |
|---|---|
| Token name | `codeatlas` |
| Expiration | 90 days |
| Repository access | **Only select repositories** → pick your scratch repo |
| Contents | **Read-only** |
| Pull requests | **Read-only** |
| Issues | **Read-only** |
| Metadata | Read-only (added automatically) |

Do not grant write permissions. CodeAtlas posts a review through this token only
after you approve a specific payload, and read-only is enough for everything up
to that point. When you later want the live posting test, temporarily set
**Pull requests: Read and write**.

Copy the token once — GitHub will not show it again.

## 2. Store the token (never paste it into a chat or a file)

From `C:\CodeAtlas`:

```powershell
uv run python -c "import keyring,getpass; keyring.set_password('codeatlas/github','pat',getpass.getpass('PAT: '))"
```

The prompt hides what you type. The token goes into Windows Credential Manager
under `codeatlas/github`, which no WSL or container process can read.

## 3. Create a scratch repository with one pull request

Anything throwaway works. The fastest route, using the GitHub CLI:

```powershell
gh auth login                     # browser flow, once
gh repo create codeatlas-scratch --private --clone
cd codeatlas-scratch
"fn main() { let v: Vec<u8> = vec![]; println!(\"{}\", v[0]); }" | Out-File -Encoding utf8 src.rs
git add -A; git commit -m "initial"; git push -u origin main
git checkout -b test-pr
"// a change to review" | Add-Content src.rs
git add -A; git commit -m "a change"; git push -u origin test-pr
gh pr create --title "CodeAtlas test" --body "For validating the review pipeline."
```

## 4. Tell me two things

- the repository as `owner/repo`
- the pull request number

Then I run, in order:

```powershell
uv run python scripts/validate_github.py <owner>/<repo> <pr>   # read-only proof of access
uv run codeatlas review-pr <owner>/<repo> <pr>                 # analyze; posts NOTHING
uv run codeatlas show-approval <id>                            # you read the exact payload
uv run codeatlas approve <id> --by "<you>" --publish           # only if you say so
```

Steps 1–3 post nothing. Only the last command can write to GitHub, and it
refuses unless the approval row says approved, publication is enabled in config,
`CODEATLAS_KILL_SWITCH` is unset, and the payload passes a secret scan.

## Revoking access

Delete the token at <https://github.com/settings/tokens>, then clear the stored
copy:

```powershell
uv run python -c "import keyring; keyring.delete_password('codeatlas/github','pat')"
```

To stop all publication without touching the token: `setx CODEATLAS_KILL_SWITCH 1`.
