<#
.SYNOPSIS
    Back up the CodeAtlas database and verify the dump is readable.

.DESCRIPTION
    A dump nobody has read is not a backup. Every run does pg_dump -Fc followed by
    pg_restore --list on the produced file: if the archive cannot be listed, the
    dump is deleted and the script fails loudly rather than leaving a corrupt file
    that looks like protection.

    Retention keeps the newest N dumps and deletes older ones only after a newer
    verified dump exists.

.EXAMPLE
    pwsh infra/backup/backup_database.ps1 -Destination C:\CodeAtlas\var\backups -Keep 7
#>
[CmdletBinding()]
param(
    [string]$Destination = "C:\CodeAtlas\var\backups",
    [string]$Database = "codeatlas",
    [string]$DbUser = "codeatlas_migrator",
    [string]$PgBin = "$env:ProgramFiles\PostgreSQL\17\bin",
    [int]$Keep = 7
)

$ErrorActionPreference = "Stop"

function Get-DbPassword {
    param([string]$Account)
    Push-Location "C:\CodeAtlas"
    try {
        $pw = & uv run python -c "import keyring; print(keyring.get_password('codeatlas/db','$Account') or '')" |
            Select-Object -Last 1
    } finally {
        Pop-Location
    }
    if ([string]::IsNullOrWhiteSpace($pw)) {
        throw "no password for codeatlas/db/$Account in Windows Credential Manager"
    }
    return $pw
}

New-Item -ItemType Directory -Force $Destination | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$dump = Join-Path $Destination "$Database-$stamp.dump"

$env:PGPASSWORD = Get-DbPassword -Account $DbUser
try {
    & "$PgBin\pg_dump.exe" -Fc -h 127.0.0.1 -U $DbUser -d $Database -f $dump
    if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }

    # Verification is not optional: an unreadable archive is worse than no backup,
    # because it is mistaken for protection.
    & "$PgBin\pg_restore.exe" --list $dump > $null
    if ($LASTEXITCODE -ne 0) {
        Remove-Item $dump -Force
        throw "pg_restore --list could not read $dump; the dump was deleted"
    }
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}

$size = [math]::Round((Get-Item $dump).Length / 1MB, 2)
Write-Output "verified backup: $dump ($size MB)"

# Prune only after a newer verified dump exists.
Get-ChildItem $Destination -Filter "$Database-*.dump" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep |
    ForEach-Object {
        Write-Output "pruning old backup: $($_.Name)"
        Remove-Item $_.FullName -Force
    }
