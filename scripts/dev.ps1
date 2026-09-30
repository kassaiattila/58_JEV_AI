# Helyi szolgaltatas + feldolgozo inditasa / leallitasa (040 K2).
#   .\scripts\dev.ps1 start    # API (127.0.0.1:8930) + egy feldolgozo, hatterben; naplo: runs\dev\*.log
#   .\scripts\dev.ps1 status   # futnak-e, es mennyi feladat var
#   .\scripts\dev.ps1 stop     # a feldolgozo a folyamatban levo tetel utan lep ki, az API azonnal all le
# A szoveg szandekosan ASCII: a Windows PowerShell 5.1 a nem ASCII literalt hibasan olvashatja (CLAUDE.md 7.).
param(
    [Parameter(Mandatory = $true)][ValidateSet("start", "stop", "status")][string]$Action,
    [int]$Port = 8930,
    [int]$StopTimeoutSec = 120
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DevDir = Join-Path $Root "runs\dev"
New-Item -ItemType Directory -Force -Path $DevDir | Out-Null

function Get-Tracked([string]$Name) {
    $pidFile = Join-Path $DevDir "$Name.pid"
    if (-not (Test-Path $pidFile)) { return $null }
    $procId = [int](Get-Content $pidFile -Raw)
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -eq $proc) { Remove-Item $pidFile -Force; return $null }
    # 066 Á38: újraindítás után a szám már egy másik programé lehet; csak a saját (jav.cli) folyamatunkat kezeljük
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if ($null -eq $cim -or $cim.CommandLine -notmatch 'jav\.cli') { Remove-Item $pidFile -Force; return $null }
    return $proc
}

function Start-Tracked([string]$Name, [string[]]$CliArgs) {
    $existing = Get-Tracked $Name
    if ($null -ne $existing) { Write-Output "$Name already running (pid $($existing.Id))"; return }
    $out = Join-Path $DevDir "$Name.log"
    $err = Join-Path $DevDir "$Name.err.log"
    # 063: az elozo inditas kimenete megmarad (*.prev), hogy egy osszeomlas nyoma ujrainditas utan is olvashato legyen;
    # az allando, forgo naplo: runs\logs\api.log es runs\logs\worker.log
    foreach ($f in @($out, $err)) { if ((Test-Path $f) -and ((Get-Item $f).Length -gt 0)) { Move-Item $f "$f.prev" -Force } }
    $proc = Start-Process -FilePath $Python -ArgumentList (@("-X", "utf8", "-m", "jav.cli") + $CliArgs) `
        -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Set-Content -Path (Join-Path $DevDir "$Name.pid") -Value $proc.Id -Encoding ascii
    Write-Output "$Name started (pid $($proc.Id)), log: $out"
}

switch ($Action) {
    "start" {
        Start-Tracked "api" @("serve", "--port", "$Port")
        Start-Tracked "worker" @("worker")
    }
    "status" {
        foreach ($name in @("api", "worker")) {
            $p = Get-Tracked $name
            if ($null -eq $p) { Write-Output "$name : not running" } else { Write-Output "$name : running (pid $($p.Id))" }
        }
        & $Python -X utf8 -m jav.cli worker-status
    }
    "stop" {
        $w = Get-Tracked "worker"
        if ($null -ne $w) {
            & $Python -X utf8 -m jav.cli worker-stop | Out-Null
            if (-not $w.WaitForExit($StopTimeoutSec * 1000)) {
                Write-Output "worker did not stop in $StopTimeoutSec s, killing (the run resumes from the saved step)"
                Stop-Process -Id $w.Id -Force
            }
            Remove-Item (Join-Path $DevDir "worker.pid") -Force -ErrorAction SilentlyContinue
            Write-Output "worker stopped"
        }
        $a = Get-Tracked "api"
        if ($null -ne $a) {
            Stop-Process -Id $a.Id -Force
            Remove-Item (Join-Path $DevDir "api.pid") -Force -ErrorAction SilentlyContinue
            Write-Output "api stopped"
        }
    }
}
