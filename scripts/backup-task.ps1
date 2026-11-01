# The store's daily backup in the Windows Task Scheduler.
#   .\scripts\backup-task.ps1 install   # daily (configs\service.json backup.schedule, 12:00); a missed run runs at the next start
#   .\scripts\backup-task.ps1 status    # the task's state, its last and next run, its last result code
#   .\scripts\backup-task.ps1 run       # run it now through the Task Scheduler (to try it)
#   .\scripts\backup-task.ps1 remove    # delete the task
# The task runs as the signed-in user, without a password (only while signed in), and opens no window (pythonw).
# What it does: python -m jav.cli backup --scheduled (a local backup and a checked copy to the second location).
# Result: store\backups\backup-status.json and runs\logs\backup.log; in the interface: Settings > System.
# Result code: 0 fine, 1 the local backup failed, 2 the local one is fine but the copy failed.
# The script's strings are ASCII on purpose: Windows PowerShell 5.1 can misread a non-ASCII literal (CLAUDE.md 7).
# The task's name below stays as it was installed (renaming it would leave the installed task behind).
param(
    [Parameter(Mandatory = $true)][ValidateSet("install", "remove", "status", "run")][string]$Action
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$TaskName = "JAV_AI napi mentes"
$PythonW = Join-Path $Root ".venv\Scripts\pythonw.exe"

function Get-Task { Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }

switch ($Action) {
    "install" {
        if (-not (Test-Path $PythonW)) { throw "Missing: $PythonW (see docs\guides\SETUP.md)" }
        $config = Get-Content (Join-Path $Root "configs\service.json") -Raw -Encoding UTF8 | ConvertFrom-Json
        $time = $config.backup.schedule
        # the variable names may not clash with the $Action parameter (PowerShell does not tell upper and lower case apart)
        $taskAction = New-ScheduledTaskAction -Execute $PythonW -Argument "-X utf8 -m jav.cli backup --scheduled" -WorkingDirectory $Root
        $taskTrigger = New-ScheduledTaskTrigger -Daily -At $time
        $taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
        $taskPrincipal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
        Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Principal $taskPrincipal `
            -Description "58_JAV_AI: napi adattar-mentes (python -m jav.cli backup --scheduled), 064" -Force | Out-Null
        Write-Output "Installed: '$TaskName' daily at $time (missed runs start at next logon/boot)."
    }
    "remove" {
        if (Get-Task) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false; Write-Output "Removed: '$TaskName'." }
        else { Write-Output "Not installed: '$TaskName'." }
    }
    "status" {
        $task = Get-Task
        if ($null -eq $task) { Write-Output "Not installed: '$TaskName'."; return }
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Output ("{0}: {1}; last run {2} (result {3}); next run {4}" -f $TaskName, $task.State, $info.LastRunTime, $info.LastTaskResult, $info.NextRunTime)
    }
    "run" {
        if ($null -eq (Get-Task)) { throw "Not installed: '$TaskName' (run: .\scripts\backup-task.ps1 install)" }
        Start-ScheduledTask -TaskName $TaskName
        Write-Output "Started: '$TaskName' (result: store\backups\backup-status.json)."
    }
}
