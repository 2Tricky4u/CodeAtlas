<#
.SYNOPSIS
    Create a scratch repository with a reviewable pull request, and store the
    GitHub token CodeAtlas will use.

.DESCRIPTION
    Everything here needs an authenticated `gh` (run `gh auth login` first).
    It creates a private throwaway repository whose base revision is correct and
    whose pull request introduces one genuine defect, so the review has something
    real to find and changed-scope enforcement has something real to distinguish.

    The token is taken from `gh auth token` and stored in Windows Credential
    Manager. That token carries gh's OAuth scopes, which are broader than the
    read-only fine-grained PAT recommended in docs/runbooks/github-access.md —
    convenient for a scratch test, worth replacing for ongoing use.

.EXAMPLE
    pwsh scripts/setup_scratch_pr.ps1 -RepoName codeatlas-scratch
#>
[CmdletBinding()]
param(
    [string]$RepoName = "codeatlas-scratch",
    [string]$WorkDir = "$env:TEMP\codeatlas-scratch"
)

$ErrorActionPreference = "Stop"

function Get-Gh {
    $candidates = @(
        "$env:ProgramFiles\GitHub CLI\gh.exe",
        "${env:ProgramFiles(x86)}\GitHub CLI\gh.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    $found = Get-Command gh -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    throw "gh not found. Install with: winget install --exact --id GitHub.cli"
}

$gh = Get-Gh
& $gh auth status *> $null
if ($LASTEXITCODE -ne 0) {
    throw "gh is not authenticated. Run '$gh auth login' first (browser flow)."
}

$account = (& $gh api user --jq .login).Trim()
$slug = "$account/$RepoName"
Write-Output "account: $account"

# --- repository -----------------------------------------------------------
& $gh repo view $slug *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Output "creating private repository $slug"
    & $gh repo create $RepoName --private --description "CodeAtlas end-to-end test scratch repository" | Out-Null
} else {
    Write-Output "repository $slug already exists; reusing it"
}

if (Test-Path $WorkDir) { Remove-Item $WorkDir -Recurse -Force }
New-Item -ItemType Directory -Force $WorkDir | Out-Null
Push-Location $WorkDir
try {
    git init -b main --quiet
    git remote add origin "https://github.com/$slug.git"

    # --- base revision: correct code ------------------------------------
    New-Item -ItemType Directory -Force "src" | Out-Null
    $baseCode = @'
//! A tiny request handler used to exercise CodeAtlas end to end.

pub enum Response {
    Ok(String),
    Error(String),
}

/// Handle a wire request of the form `get:<key>`.
///
/// Requests arrive from the network and are untrusted.
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
'@
    [System.IO.File]::WriteAllText("$WorkDir\src\lib.rs", $baseCode, (New-Object System.Text.UTF8Encoding $false))

    $cargo = @'
[package]
name = "scratch"
version = "0.1.0"
edition = "2021"

[dependencies]
'@
    [System.IO.File]::WriteAllText("$WorkDir\Cargo.toml", $cargo, (New-Object System.Text.UTF8Encoding $false))

    $readme = @'
# scratch

A throwaway repository for validating the CodeAtlas review pipeline end to end.
The pull request on the `review-me` branch deliberately introduces one defect.
'@
    [System.IO.File]::WriteAllText("$WorkDir\README.md", $readme, (New-Object System.Text.UTF8Encoding $false))

    git add -A
    git commit -m "Add the request handler" --quiet
    git push -u origin main --quiet 2>&1 | Out-Null
    Write-Output "pushed base revision"

    # --- pull request: introduces a real defect --------------------------
    git checkout -b review-me --quiet
    $prCode = $baseCode.Replace(
        @'
        Some("get") => match parts.next() {
            Some(key) => Response::Ok(key.to_string()),
            None => Response::Error("missing key".to_string()),
        },
'@,
        @'
        Some("get") => {
            let key = parts.next().unwrap();
            Response::Ok(key.to_string())
        }
'@)
    if ($prCode -eq $baseCode) { throw "failed to build the PR revision" }
    [System.IO.File]::WriteAllText("$WorkDir\src\lib.rs", $prCode, (New-Object System.Text.UTF8Encoding $false))

    git add -A
    git commit -m "Simplify the get arm" --quiet
    git push -u origin review-me --quiet 2>&1 | Out-Null

    & $gh pr create --title "Simplify the get arm" `
        --body "Tidies up the get branch of the request handler." `
        --base main --head review-me | Out-Null
    $prNumber = (& $gh pr view review-me --json number --jq .number).Trim()
    Write-Output "opened pull request #$prNumber"
} finally {
    Pop-Location
}

# --- token ----------------------------------------------------------------
$token = (& $gh auth token).Trim()
if (-not $token) { throw "gh auth token returned nothing" }
Push-Location "C:\CodeAtlas"
try {
    $env:CODEATLAS_GH_TOKEN = $token
    uv run python -c "import keyring, os; keyring.set_password('codeatlas/github','pat', os.environ['CODEATLAS_GH_TOKEN']); print('token stored in Credential Manager under codeatlas/github')"
} finally {
    Remove-Item Env:\CODEATLAS_GH_TOKEN -ErrorAction SilentlyContinue
    Pop-Location
}

Write-Output ""
Write-Output "READY"
Write-Output "  repository: $slug"
Write-Output "  pull request: $prNumber"
Write-Output ""
Write-Output "Next (read-only, posts nothing):"
Write-Output "  uv run python scripts/validate_github.py $slug $prNumber"
Write-Output "  uv run codeatlas review-pr $slug $prNumber"
