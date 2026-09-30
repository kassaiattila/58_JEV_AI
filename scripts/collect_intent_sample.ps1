# Read-only Outlook sample collector. Account resolution/sorted scanning adapted from
# 10_AIFLOW_V4/scripts/outlook_bridge.ps1; no POST, archive, mailbox writes or scheduler.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string[]]$Accounts,
    [Parameter(Mandatory=$true)][string]$OutputRoot,
    [Parameter(Mandatory=$true)][string]$ExcludeIds,
    [ValidateRange(1,100)][int]$PerAccount=30,
    [ValidateRange(1,2000)][int]$ScanLimit=1000,
    [ValidateRange(1,730)][int]$SinceDays=365
)
$ErrorActionPreference='Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$root = [IO.Path]::GetFullPath($OutputRoot)
$workspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..')) + [IO.Path]::DirectorySeparatorChar
if (-not $root.StartsWith($workspace,[StringComparison]::OrdinalIgnoreCase)) { throw 'Output must stay inside workspace' }
if (Test-Path -LiteralPath $root) { throw 'Use a new empty sample directory' }
$excluded = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
foreach ($id in ([IO.File]::ReadAllText($ExcludeIds,$utf8) | ConvertFrom-Json)) { [void]$excluded.Add([string]$id) }
$app = [Runtime.InteropServices.Marshal]::GetActiveObject('Outlook.Application')
$ns = $app.GetNamespace('MAPI')
$targets = @()
foreach ($requested in $Accounts) {
    $matched = @($ns.Accounts | Where-Object { $_.SmtpAddress -ieq $requested })
    if ($matched.Count -ne 1) { throw 'Requested account must match exactly one existing Outlook account' }
    $targets += [pscustomobject]@{ smtp=$requested; inbox=$matched[0].DeliveryStore.GetDefaultFolder(6) }
}
[void][IO.Directory]::CreateDirectory($root)
$cutoff=(Get-Date).AddDays(-$SinceDays)
$report=@()
foreach ($target in $targets) {
    $items=$target.inbox.Items
    $items.Sort('[ReceivedTime]',$true)
    $scanned=0; $saved=0; $skipped=0
    for ($index=1; $index -le $items.Count -and $scanned -lt $ScanLimit -and $saved -lt $PerAccount; $index++) {
        $item=$items.Item($index)
        try {
            if ($item.Class -ne 43) { continue }
            $scanned++
            if ($item.ReceivedTime -lt $cutoff) { break }
            $entry=[string]$item.EntryID
            if ($excluded.Contains($entry)) { $skipped++; continue }
            $sha=[Security.Cryptography.SHA256]::Create()
            try { $id=([BitConverter]::ToString($sha.ComputeHash($utf8.GetBytes($target.smtp+'|'+$entry)))).Replace('-','').ToLowerInvariant() }
            finally { $sha.Dispose() }
            $folder=Join-Path $root $id
            [void][IO.Directory]::CreateDirectory($folder)
            $body=[string]$item.Body
            $rawLength=$body.Length
            if ($body.Length -gt 20000) { $body=$body.Substring(0,20000) }
            $atts=@()
            for ($n=1; $n -le $item.Attachments.Count; $n++) {
                $att=$item.Attachments.Item($n)
                try { $atts += [ordered]@{filename=[string]$att.FileName; path=$null; status='name_only'; size=[long]$att.Size} }
                finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($att) }
            }
            $sender=[string]$item.SenderEmailAddress
            if ($item.SenderEmailType -eq 'EX') {
                try { $sender=[string]$item.Sender.GetExchangeUser().PrimarySmtpAddress } catch {}
            }
            $row=[ordered]@{message_id=$entry; entry_id=$entry; mailbox=$target.smtp;
                sender=$sender; sender_name=[string]$item.SenderName; subject=[string]$item.Subject;
                received_at=$item.ReceivedTime.ToString('o'); body=$body; attachments=$atts;
                raw_body_chars=$rawLength; body_truncated=($rawLength -gt 20000);
                attachment_content_retrieved=$false; source='existing_outlook_readonly'; sampled_at=(Get-Date).ToString('o')}
            [IO.File]::WriteAllText((Join-Path $folder 'message.json'),($row | ConvertTo-Json -Depth 8),$utf8)
            [void]$excluded.Add($entry)
            $saved++
        } finally { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($item) }
    }
    $report += [ordered]@{account=$target.smtp; scanned=$scanned; saved=$saved; skipped_existing=$skipped}
    Write-Output ('account {0}: saved={1} scanned={2} existing={3}' -f $report.Count,$saved,$scanned,$skipped)
}
[IO.File]::WriteAllText((Join-Path $root 'collection.json'),(@{accounts=$report;per_account=$PerAccount;scan_limit=$ScanLimit;since_days=$SinceDays;mailbox_mutations=0;attachments='metadata_only'} | ConvertTo-Json -Depth 8),$utf8)
