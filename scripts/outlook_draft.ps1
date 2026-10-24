# 231 (plan stage A, A8; DECISIONS 231): puts one prepared message into the desktop Outlook of the person working, as a
# draft in their Drafts folder (jav/domains/email/outlook_drafts.py calls it). With -Send it sends the message instead;
# the caller passes -Send only for a process pack whose send mode is the real send, and only to recipients on the
# owner's allowlist (configs/send.json). The mailbox download (outlook_bridge.ps1) stays read-only: this is the only
# script that writes into Outlook.
#   -Request : a UTF-8 JSON file: to, subject, body (plain text), attachments (file paths)
# Output: one JSON line: {"ok": true, "state": "draft"|"sent", "entry_id": ...} or {"ok": false, "refused": true, ...}.
# Exit codes: 0 done; 3 refused before anything was written (Outlook is not running here); any other: unknown outcome.
param(
    [Parameter(Mandatory = $true)][string]$Request,
    [switch]$Send
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)

$req = Get-Content -LiteralPath $Request -Raw -Encoding UTF8 | ConvertFrom-Json

# Outlook must already run in this interactive session (as for the mailbox download): nothing is started or written
# otherwise.
$currentSession = (Get-Process -Id $PID).SessionId
$running = @(Get-Process OUTLOOK -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $currentSession })
if ($running.Count -eq 0) {
    Write-Output (@{ ok = $false; refused = $true; error = 'Outlook is not running in this session' } | ConvertTo-Json -Compress)
    exit 3
}

$ol = New-Object -ComObject Outlook.Application
$mail = $ol.CreateItem(0)
if ($req.to) { $mail.To = [string]$req.to }
$mail.Subject = [string]$req.subject
$mail.Body = [string]$req.body
foreach ($path in @($req.attachments)) {
    if ($path) { [void]$mail.Attachments.Add([string]$path) }
}
if ($Send) {
    $mail.Send()
    Write-Output (@{ ok = $true; state = 'sent' } | ConvertTo-Json -Compress)
} else {
    $mail.Save()
    Write-Output (@{ ok = $true; state = 'draft'; entry_id = [string]$mail.EntryID } | ConvertTo-Json -Compress)
}
