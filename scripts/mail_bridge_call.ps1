# A régi Outlook-szkript (10_AIFLOW_V4/scripts/outlook_bridge.ps1) hívása VÁLTOZATLANUL, a helyi szolgáltatásból
# (048 T2, jav/mailbox.py). Csak a paramétereket rakja össze, és a darabszám-előnézet eredményét JSON-ként adja vissza.
#   -Mode count : ingyenes előnézet (a régi -CountOnly), fájlt nem ír, semmit nem küld; kimenet: egy JSON-sor
#   -Mode fetch : letöltés; a levelek a megadott fogadóra mennek (-OrchUrl, -ApiToken), a naplósorok a kimenetre
# Mindig: -ManualRun (nincs régi beállításfájl), -ExistingOutlook (az Outlooknak futnia kell), -NoArchive, -AllEmails
# (2026-09-28 döntés: minden levél), -RepoRoot a saját repó bridge-gyökere (a régi projekt csak olvasható).
param(
    [Parameter(Mandatory = $true)][string]$Script,
    [Parameter(Mandatory = $true)][ValidateSet('count', 'fetch')][string]$Mode,
    [Parameter(Mandatory = $true)][string]$Accounts,        # vesszővel elválasztva
    [string]$Folders = 'Inbox',                             # vesszővel elválasztva
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
