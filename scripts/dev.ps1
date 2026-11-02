# Starts and stops the local service and its workers.
#   .\scripts\dev.ps1 start    # the API (127.0.0.1:8930) and the workers in the background; logs: runs\dev\*.log
#                              # it waits until the API answers, and says why if it stopped (exit code 1)
#                              # as many workers as configs\service.json "workers" says (one by default)
#                              # also the invented registers (127.0.0.1:8941) the insurance case asks
#   .\scripts\dev.ps1 status   # whether they run, and how many jobs wait
#   .\scripts\dev.ps1 stop     # a worker leaves after the item it is working on, the API stops at once
# The script's strings are ASCII on purpose: Windows PowerShell 5.1 can misread a non-ASCII literal (CLAUDE.md 7).
param(
    [Parameter(Mandatory = $true)][ValidateSet("start", "stop", "status")][string]$Action,
    [int]$Port = 8930,
    [int]$StopTimeoutSec = 120,
    [int]$StartTimeoutSec = 90
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$DevDir = Join-Path $Root "runs\dev"
New-Item -ItemType Directory -Force -Path $DevDir | Out-Null

# 231 (E1): the workers the service configuration allows: "worker" is slot 1, then "worker-2", "worker-3" ...
$WorkerCount = 1
try { $WorkerCount = [int]((Get-Content (Join-Path $Root "configs\service.json") -Raw | ConvertFrom-Json).workers) } catch { $WorkerCount = 1 }
if ($WorkerCount -lt 1) { $WorkerCount = 1 }
$WorkerNames = @(1..$WorkerCount | ForEach-Object { if ($_ -eq 1) { "worker" } else { "worker-$_" } })

function Get-Tracked([string]$Name) {
    $pidFile = Join-Path $DevDir "$Name.pid"
    if (-not (Test-Path $pidFile)) { return $null }
    $procId = [int](Get-Content $pidFile -Raw)
    $proc = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if ($null -eq $proc) { Remove-Item $pidFile -Force; return $null }
    # 066 Á38: after a restart the number may be another program's; only our own (jav.cli) processes are handled
    $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue
    if ($null -eq $cim -or $cim.CommandLine -notmatch 'jav\.cli') { Remove-Item $pidFile -Force; return $null }
    return $proc
}

function Start-Tracked([string]$Name, [string[]]$CliArgs) {
    $existing = Get-Tracked $Name
    if ($null -ne $existing) { Write-Output "$Name already running (pid $($existing.Id))"; return }
    $out = Join-Path $DevDir "$Name.log"
    $err = Join-Path $DevDir "$Name.err.log"
    # the previous start's output is kept (*.prev), so a crash's trace can still be read after a restart; the lasting,
    # rotating logs are runs\logs\api.log and runs\logs\worker.log
    foreach ($f in @($out, $err)) { if ((Test-Path $f) -and ((Get-Item $f).Length -gt 0)) { Move-Item $f "$f.prev" -Force } }
    $proc = Start-Process -FilePath $Python -ArgumentList (@("-X", "utf8", "-m", "jav.cli") + $CliArgs) `
        -WorkingDirectory $Root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
    Set-Content -Path (Join-Path $DevDir "$Name.pid") -Value $proc.Id -Encoding ascii
    Write-Output "$Name started (pid $($proc.Id)), log: $out"
}

function Wait-Api([int]$TimeoutSec) {
    # 278: "started" is said only once the service answers; a service that stopped at start-up says why (on a new
    # machine the usual reasons are a taken port or a missing package) instead of leaving it to the log files; the
    # outcome goes into $script:ApiUp (a function's return value would be mixed into the lines it prints)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ($null -eq (Get-Tracked "api")) {
            Write-Output "api stopped at start-up:"
            foreach ($f in @((Join-Path $DevDir "api.err.log"), (Join-Path $DevDir "api.log"))) {
                if ((Test-Path $f) -and ((Get-Item $f).Length -gt 0)) { Get-Content $f -Tail 5 -Encoding UTF8 | ForEach-Object { Write-Output "  $_" } }
            }
            Write-Output "  the service's own log: $(Join-Path $Root 'runs\logs\api.log')"
            $script:ApiUp = $false
            return
        }
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { Write-Output "api answers: http://127.0.0.1:$Port/"; $script:ApiUp = $true; return }
        } catch {
            # not listening yet: it is still loading its code
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Output "api does not answer after $TimeoutSec s; see $(Join-Path $DevDir 'api.log') and runs\logs\api.log"
    $script:ApiUp = $false
}

function Invoke-Cli([string[]]$CliArgs) {
    # 139: jav.cli is only importable from the project root, so the script may be started from any folder
    Push-Location $Root
    try { & $Python -X utf8 -m jav.cli @CliArgs } finally { Pop-Location }
}

switch ($Action) {
    "start" {
        Start-Tracked "api" @("serve", "--port", "$Port")
        $script:ApiUp = $false
        Wait-Api $StartTimeoutSec
        for ($slot = 1; $slot -le $WorkerCount; $slot++) { Start-Tracked $WorkerNames[$slot - 1] @("worker", "--slot", "$slot") }
        Start-Tracked "registers" @("invented-services")
        if (-not $script:ApiUp) { exit 1 }
    }
    "status" {
        foreach ($name in (@("api") + $WorkerNames + @("registers"))) {
            $p = Get-Tracked $name
            if ($null -eq $p) { Write-Output "$name : not running" } else { Write-Output "$name : running (pid $($p.Id))" }
        }
        Invoke-Cli @("worker-status")
    }
    "stop" {
        $running = @($WorkerNames | ForEach-Object { $p = Get-Tracked $_; if ($null -ne $p) { [pscustomobject]@{ Name = $_; Proc = $p } } })
        if ($running.Count -gt 0) {
            # one request stops every worker after its item in progress
            Invoke-Cli @("worker-stop") | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Output "worker-stop request failed (exit $LASTEXITCODE); waiting for the workers anyway" }
            foreach ($r in $running) {
                if (-not $r.Proc.WaitForExit($StopTimeoutSec * 1000)) {
                    Write-Output "$($r.Name) did not stop in $StopTimeoutSec s, killing (the run resumes from the saved step)"
                    Stop-Process -Id $r.Proc.Id -Force
                }
                Remove-Item (Join-Path $DevDir "$($r.Name).pid") -Force -ErrorAction SilentlyContinue
                Write-Output "$($r.Name) stopped"
            }
        }
        foreach ($name in @("api", "registers")) {
            $a = Get-Tracked $name
            if ($null -ne $a) {
                Stop-Process -Id $a.Id -Force
                Remove-Item (Join-Path $DevDir "$name.pid") -Force -ErrorAction SilentlyContinue
                Write-Output "$name stopped"
            }
        }
    }
}
