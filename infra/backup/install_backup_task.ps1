<#
.SYNOPSIS
    Register the nightly CodeAtlas database backup as a Windows scheduled task.

.DESCRIPTION
    Runs backup_database.ps1 nightly. The task runs as the current user so it can
    read the database password from that user's Credential Manager — a backup job
    running as SYSTEM would have no access to it.

    Run this from an elevated shell if the task must survive user logoff.
#>
[CmdletBinding()]
param(
    [string]$Time = "02:30",
    [string]$TaskName = "CodeAtlas nightly database backup"
)

$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "backup_database.ps1"
if (-not (Test-Path $script)) { throw "missing $script" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -Daily -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "pg_dump + pg_restore --list verification" -Force |
    Out-Null

Write-Output "registered '$TaskName' daily at $Time"
Write-Output "verify with: Get-ScheduledTask -TaskName '$TaskName'"
Write-Output "run once now: Start-ScheduledTask -TaskName '$TaskName'"
