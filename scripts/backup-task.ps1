# Napi adattar-mentes a Windows Feladatutemezoben (064, dontes 2026-09-29).
#   .\scripts\backup-task.ps1 install   # naponta (configs\service.json backup.schedule, 12:00); kimaradaskor a kovetkezo bekapcsolaskor
#   .\scripts\backup-task.ps1 status    # a feladat allapota, utolso es kovetkezo futas, utolso eredmenykod
#   .\scripts\backup-task.ps1 run       # azonnali futtatas a Feladatutemezon at (probahoz)
#   .\scripts\backup-task.ps1 remove    # a feladat torlese
# A feladat a bejelentkezett felhasznalo neveben fut, jelszo nelkul (csak bejelentkezve), ablakot nem nyit (pythonw).
# Mit csinal: python -m jav.cli backup --scheduled (helyi mentes + ellenorzott masolat a NAS-ra, 14 marad).
# Eredmeny: store\backups\backup-status.json es runs\logs\backup.log; a feluleten: Beallitasok > Rendszer.
# Eredmenykod: 0 rendben, 1 a helyi mentes hibas, 2 a helyi rendben, de a masolat nem sikerult.
# A szoveg szandekosan ASCII: a Windows PowerShell 5.1 a nem ASCII literalt hibasan olvashatja (CLAUDE.md 7.).
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
        # a valtozonevek nem utkozhetnek a $Action parameterrel (a PowerShell nem kulonbozteti meg a kis- es nagybetut)
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
