# Calls the Outlook script (scripts/outlook_bridge.ps1, 148: ported from 10_AIFLOW_V4) from the local service
# (048 T2, jav/domains/email/mailbox.py). It only assembles the parameters and returns the count preview's result as JSON.
#   -Mode count : a free preview (the legacy -CountOnly), writes no file, sends nothing; output: one JSON line
#   -Mode fetch : the download; the emails go to the receiver given (-OrchUrl, -ApiToken), the log lines to the output
# Always: -ManualRun (no legacy settings file), -ExistingOutlook (Outlook must be running), -NoArchive, -AllEmails
# (the decision of 2026-09-28: every email), -RepoRoot the own repository's bridge root (the legacy project is read only).
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][ValidateSet('count', 'fetch')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$Accounts,        # comma-separated
    [string]$Folders = 'Inbox',                             # comma-separated
    [switch]$Subfolders,
    [int]$SinceDays = 0,
    [string]$ReceivedFrom = '',
    [string]$ReceivedTo = '',
    [int]$MaxItems = 0,
    [string]$OrchUrl = '',
    [string]$ApiToken = '',
    [Parameter(Mandatory = $true)][string]$RepoRoot
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$p = @{
    Accounts       = @($Accounts -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    MailFolders    = @($Folders -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
    MaxItems       = $MaxItems
    RepoRoot       = $RepoRoot
    ManualRun      = $true
    ExistingOutlook = $true
    NoArchive      = $true
    AllEmails      = $true
    WorkflowId     = 'email-intent'
    WorkflowVersion = 1
}
if ($Subfolders) { $p.Subfolders = $true }
if ($ReceivedFrom -and $ReceivedTo) {
    $p.PeriodMode = 'interval'; $p.ReceivedFrom = $ReceivedFrom; $p.ReceivedTo = $ReceivedTo
} else {
    $p.PeriodMode = 'recent'; $p.SinceDays = [Math]::Max(1, $SinceDays)
}

if ($Mode -eq 'count') {
    $p.CountOnly = $true
    $out = & $Script @p 6>$null
    $obj = @($out | Where-Object { $_ -and $_.PSObject.Properties.Name -contains 'count_only' }) | Select-Object -Last 1
    if (-not $obj) { throw 'The bridge returned no count result.' }
    $obj | ConvertTo-Json -Depth 6 -Compress
} else {
    $p.OrchUrl = $OrchUrl
    if ($ApiToken) { $p.ApiToken = $ApiToken }
    & $Script @p 6>&1 | ForEach-Object { "$_" }
}
