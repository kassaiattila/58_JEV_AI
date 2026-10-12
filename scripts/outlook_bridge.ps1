<#
.SYNOPSIS
  AIFLOW V4 - local Outlook -> /ingest/email bridge (READ-ONLY).

.DESCRIPTION
  Reads mail from the locally-configured desktop Outlook (COM/MAPI) for the target accounts,
  drops qualifying document attachments under the shared repo `data/` dir, archives the raw
  .msg + attachments to the NAS, and POSTs one job per email to the orchestrator /ingest/email
  webhook. The orchestrator enqueues (bare.jobs, dedup on email:<EntryID>) and the worker pool
  runs email-intake -> (invoice/bank) doc-extract under the daily spend cap.

  STRICTLY READ-ONLY on the mailbox: never marks read, never moves/deletes, never sends.
  The attachment path emitted is the SIDECAR-visible container path `/data/<sub>/<file>`
  (verified path contract); the file is dropped on the host BEFORE the POST.

.NOTES
  UTF-8 discipline (PS5.1): the POST body is sent as UTF-8 bytes; files are written via
  System.IO with UTF8Encoding(no BOM). Outlook must be running in the same interactive session.
#>
[CmdletBinding()]
param(
    # EMPTY BY DEFAULT, and that is load-bearing. Three real mailbox addresses used to sit here as the
    # default, in a git-tracked file (the secret-scan only reads .md/.json, so it never saw them). On a
    # clone with no intake-settings.json the bridge fell back to the PREVIOUS OWNER's mailboxes and
    # scanned them. The real source is data/intake-settings.json (per host, gitignored) or -Accounts.
    [string[]]$Accounts = @(),
    [string[]]$MailFolders = @('Inbox'),
    [int]$SinceDays = 183,                                   # ~6 months (go-gate decision)
    [ValidateSet('recent','interval')]
    [string]$PeriodMode = 'recent',
    [string]$ReceivedFrom = '',
    [string]$ReceivedTo = '',
    [int]$MaxItems = 0,                                      # 0 = no cap; else stop after N processed
    [int]$MaxAttachRetries = 3,                              # s27/CH3: save-retries before giving up on a partial email
    [switch]$AllEmails,                                      # off (default) = only emails WITH a doc attachment
    [switch]$DryRun,                                         # build+archive but DO NOT POST / DO NOT mark seen
    [switch]$CountOnly,                                      # metadata counts only; no files, archive, POST, or seen writes
    [switch]$ExistingOutlook,                                # one-off requests must use an already-running desktop Outlook
    [switch]$ManualRun,                                      # run from the UI without enabling the recurring schedule
    [switch]$Force,                                          # re-process EntryIDs already in the local seen-set
    [ValidateSet('auto','azure')]
    [string]$OcrPolicy = 'auto',
    [string]$WorkflowId = '',
    [int]$WorkflowVersion = 0,
    [string]$WorkflowHash = '',
    [switch]$NoArchive,                                      # skip the NAS raw-email archive
    [switch]$Subfolders,                                     # also scan Inbox subfolders (default: Inbox only)
    [string]$OrchUrl = 'http://localhost:8901/ingest/email',
    # DERIVED from this script's own location, like every sibling script in scripts/. It used to be the
    # absolute path of the development machine with NO fallback, and no caller passes -RepoRoot: cloned
    # anywhere else, the bridge read a non-existent config, skipped the whole settings block, and wrote
    # attachments into a phantom C:\ tree while POSTing container paths that did not match -- with the
    # dead-man indicator staying GREEN throughout.
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
    # Empty = no NAS archive (the run continues; the archive is optional by design).
    [string]$NasRoot = '',
    [string]$ConfigPath = '',
    # D-14: inbound Bearer for the orchestrator. Empty = no Authorization header (dev parity — the
    # orchestrator's auth is default-OFF, so an unauthenticated POST is correct there). Resolution order:
    # this parameter -> $env:ORCH_API_TOKEN -> the ORCH_API_TOKEN line in <RepoRoot>\.env. The .env
    # fallback exists because that file is where the operator ALREADY sets the token for the containers;
    # requiring them to also export it into the scheduled-task environment is how the two drift apart.
    [string]$ApiToken = ''
)

$ErrorActionPreference = 'Stop'
# NOTE: no Set-StrictMode — it false-positives on COM collections (.Count) + our defensive try/catch pattern.

# ---------------------------------------------------------------- constants
# Ü7.5/CH4 — DELIBERATELY NARROWER than the orchestrator's channels.INGESTIBLE SoR (which also accepts
# .docx/.xlsx). This is a decision, not drift: the bridge is the ONLY component reading a live Outlook
# mailbox, so it is the untrusted-input frontier, and an Office attachment is a macro/OLE carrier class
# that PDFs and images are not. Everything the bridge does save is re-filtered downstream against the SoR
# anyway (K.INGESTIBLE in email-intake), so this list can only ever be a SUBSET — never a widening.
# To ingest Office attachments from email, widen HERE first, then re-measure the intent golden (the
# attachment text feeds the classify prompt, so it is NOT a golden-neutral change).
$DOC_EXTS = @('.pdf', '.jpg', '.jpeg', '.png', '.tif', '.tiff')
$MIN_ATTACH_BYTES = 8192                                     # skip tiny inline/signature logos
# s26: full email text (was 2000 = truncated). 20000 chars (~5000 tokens) covers a full business email
# while bounding the intent-classify token cost against a pathological huge thread.
$BODY_PREVIEW_CHARS = 20000
$OL_MAIL_CLASS = 43                                          # olMail
$OL_FOLDER_INBOX = 6                                         # olFolderInbox
$OL_BY_VALUE = 1                                             # olByValue (real file attachment)
$OL_SAVE_MSG_UNICODE = 9                                     # olMSGUnicode
$DATA_DIR = Join-Path $RepoRoot 'data'
$TMP_DIR = Join-Path $DATA_DIR 'tmp'
$SEEN_FILE = Join-Path $TMP_DIR 'outlook_bridge_seen.txt'
$AZURE_SEEN_FILE = Join-Path $TMP_DIR 'outlook_bridge_azure_seen.txt'
$LEDGER_FILE = Join-Path $TMP_DIR 'outlook_bridge_ledger.jsonl'
$RETRY_FILE = Join-Path $TMP_DIR 'outlook_bridge_retry.txt'   # s27/CH3: append-per-attempt; occurrences = save-retry count
$UTF8_NOBOM = New-Object System.Text.UTF8Encoding($false)

# UI-managed defaults. Explicit command-line parameters always win, preserving operational scripts.
$workflowOverride = $PSBoundParameters.ContainsKey('WorkflowId') -or $PSBoundParameters.ContainsKey('WorkflowVersion')
if ($workflowOverride -and (-not $WorkflowId -or $WorkflowVersion -lt 1)) { throw 'WorkflowId and a positive WorkflowVersion are required together.' }
if (-not $workflowOverride) { $WorkflowId = 'document-extraction'; $WorkflowVersion = 1 }
if (-not $ConfigPath) { $ConfigPath = Join-Path $DATA_DIR 'intake-settings.json' }
if (Test-Path -LiteralPath $ConfigPath) {
    try {
        $uiConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $ConfigPath | ConvertFrom-Json
        $mailConfig = $uiConfig.email
        if ($mailConfig) {
            if (-not $workflowOverride) {
                if ($mailConfig.PSObject.Properties.Name -contains 'workflow_id') { $WorkflowId = [string]$mailConfig.workflow_id }
                if ($null -ne $mailConfig.workflow_version) { $WorkflowVersion = [int]$mailConfig.workflow_version }
            }
            if ((-not $PSBoundParameters.ContainsKey('Accounts')) -and @($mailConfig.accounts).Count) { $Accounts = @($mailConfig.accounts) }
            if ((-not $PSBoundParameters.ContainsKey('MailFolders')) -and @($mailConfig.folders).Count) { $MailFolders = @($mailConfig.folders) }
            if (-not $PSBoundParameters.ContainsKey('SinceDays')) { $SinceDays = [int]$mailConfig.since_days }
            if (-not $PSBoundParameters.ContainsKey('PeriodMode')) {
                $PeriodMode = if ($mailConfig.period_mode) { [string]$mailConfig.period_mode }
                              elseif ($mailConfig.received_from -or $mailConfig.received_to) { 'interval' }
                              else { 'recent' }
            }
            if (-not $PSBoundParameters.ContainsKey('ReceivedFrom')) { $ReceivedFrom = [string]$mailConfig.received_from }
            if (-not $PSBoundParameters.ContainsKey('ReceivedTo')) { $ReceivedTo = [string]$mailConfig.received_to }
            if (-not $PSBoundParameters.ContainsKey('MaxItems')) { $MaxItems = [int]$mailConfig.max_items }
            if (-not $PSBoundParameters.ContainsKey('AllEmails')) { $AllEmails = [bool]$mailConfig.all_emails }
            if ((-not $PSBoundParameters.ContainsKey('Subfolders')) -and @($mailConfig.folders).Count -gt 1) { $Subfolders = $true }
            if ((-not $mailConfig.enabled) -and (-not $DryRun) -and (-not $CountOnly) -and (-not $ManualRun)) {
                Write-Host 'Email intake is disabled in the UI configuration.' -ForegroundColor DarkYellow
                return
            }
        }
    } catch { throw "Invalid intake settings at '$ConfigPath': $($_.Exception.Message)" }
}

# The two guards below live OUTSIDE the Test-Path block on purpose. Both used to be reachable only
# when the config file existed, which meant a fresh install -- the exact case they should protect --
# skipped them: the bridge started, scanned whatever mailboxes were hardcoded, and reported success.
if (-not $Accounts -or @($Accounts).Count -eq 0) {
    throw "No mailbox configured. Set the email accounts in '$ConfigPath' or pass -Accounts."
}
if (-not $WorkflowId -or $WorkflowVersion -lt 1) { throw 'Invalid email workflow selection.' }
if (-not (Test-Path -LiteralPath $ConfigPath) -and -not $DryRun -and -not $CountOnly -and -not $ManualRun) {
    Write-Host "No intake settings at '$ConfigPath' -- email intake is not configured on this host." -ForegroundColor DarkYellow
    Write-Host "Pass -ManualRun for a one-off run with explicit parameters." -ForegroundColor DarkGray
    return
}

# ---------------------------------------------------------------- helpers
function Get-SafeName([string]$s, [int]$max = 80) {
    if (-not $s) { return 'x' }
    $out = ($s.ToCharArray() | ForEach-Object {
            if ([char]::IsLetterOrDigit($_) -or $_ -eq '.' -or $_ -eq '-' -or $_ -eq '_') { $_ } else { '_' }
        }) -join ''
    $out = $out.Trim('_')
    if (-not $out) { $out = 'x' }
    if ($out.Length -gt $max) { $out = $out.Substring(0, $max) }
    return $out
}

function Get-ShortHash([string]$s, [int]$len = 16) {
    # EntryIDs share a long common store/folder PREFIX (unique part is at the tail) -> hash the whole thing
    # so each email gets its OWN drop dir (a first-N-chars truncation collides across items in one store).
    $md5 = [System.Security.Cryptography.MD5]::Create()
    $bytes = $md5.ComputeHash([System.Text.Encoding]::UTF8.GetBytes([string]$s))
    $hex = ($bytes | ForEach-Object { $_.ToString('x2') }) -join ''
    return $hex.Substring(0, [Math]::Min($len, $hex.Length))
}

function Get-SenderSmtp($item) {
    # Robust sender SMTP resolution - Exchange senders report an /O=.../CN= legacyDN, not an SMTP addr.
    try {
        $addr = $item.SenderEmailAddress
        if ($addr -and ($addr -notlike '/O=*') -and ($addr -notlike '/o=*')) { return $addr }
        try { $ex = $item.Sender.GetExchangeUser(); if ($ex -and $ex.PrimarySmtpAddress) { return $ex.PrimarySmtpAddress } } catch {}
        try {
            $pa = $item.PropertyAccessor
            $smtp = $pa.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E')  # PR_SMTP_ADDRESS
            if ($smtp) { return $smtp }
        } catch {}
        return $addr
    } catch { return $null }
}

function Get-RecipientsSmtp($item, $rtype) {
    # s26: SMTP addresses of the item's recipients of a given Outlook type (1=olTo, 2=olCC). Exchange
    # recipients report an /O=.../CN= legacyDN, resolved via GetExchangeUser / PR_SMTP_ADDRESS (mirrors
    # Get-SenderSmtp). Robust: any per-recipient failure is skipped, never breaks ingestion.
    $out = @()
    try {
        foreach ($r in $item.Recipients) {
            try {
                if ($r.Type -ne $rtype) { continue }
                $addr = $r.Address
                if ($addr -and ($addr -notlike '/O=*') -and ($addr -notlike '/o=*')) { $out += $addr; continue }
                try { $ex = $r.AddressEntry.GetExchangeUser(); if ($ex -and $ex.PrimarySmtpAddress) { $out += $ex.PrimarySmtpAddress; continue } } catch {}
                try {
                    $smtp = $r.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x39FE001E')
                    if ($smtp) { $out += $smtp; continue }
                } catch {}
                if ($addr) { $out += $addr }
            } catch {}
        }
    } catch {}
    return @($out)
}

function Test-DocAttachment($att) {
    try {
        if ($att.Type -ne $OL_BY_VALUE) { return $false }
        $ext = [System.IO.Path]::GetExtension([string]$att.FileName).ToLower()
        if ($DOC_EXTS -notcontains $ext) { return $false }
        if ([int]$att.Size -lt $MIN_ATTACH_BYTES) { return $false }
        # skip inline/embedded images (signature logos, banners): they are marked PR_ATTACHMENT_HIDDEN=True.
        # Real file attachments (incl. forwarded PDFs) have the property ABSENT -> GetProperty throws -> keep.
        # (Content-ID is NOT a usable discriminator: forwarded real PDFs also carry one.)
        try {
            $hidden = $att.PropertyAccessor.GetProperty('http://schemas.microsoft.com/mapi/proptag/0x7FFE000B')
            if ($hidden -eq $true) { return $false }
        } catch { }
        return $true
    } catch { return $false }
}

function Load-Seen([string]$Path = $SEEN_FILE) {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if (Test-Path $Path) {
        foreach ($line in [System.IO.File]::ReadAllLines($Path)) {
            $t = $line.Trim(); if ($t) { [void]$set.Add($t) }
        }
    }
    return , $set   # leading comma: prevent PowerShell from unrolling the (enumerable) HashSet on return
}

function Add-Seen([string]$entryId, [string]$Path = $SEEN_FILE) {
    [System.IO.File]::AppendAllText($Path, $entryId + "`n", $UTF8_NOBOM)
}

function Write-Ledger([hashtable]$row) {
    $json = ($row | ConvertTo-Json -Depth 6 -Compress)
    [System.IO.File]::AppendAllText($LEDGER_FILE, $json + "`n", $UTF8_NOBOM)
}

function Load-RetryCounts {
    # s27/CH3: EntryID -> save-retry attempt count. Append-and-tally (mirrors the seen-file idiom): each
    # partial-save attempt appends the EntryID, so the count is the number of occurrences.
    $map = @{}
    if (Test-Path $RETRY_FILE) {
        foreach ($line in [System.IO.File]::ReadAllLines($RETRY_FILE)) {
            $t = $line.Trim(); if ($t) { $map[$t] = ([int]$map[$t]) + 1 }
        }
    }
    return $map
}

function Add-Retry([string]$entryId) {
    [System.IO.File]::AppendAllText($RETRY_FILE, $entryId + "`n", $UTF8_NOBOM)
}

function Resolve-ApiToken([string]$explicit, [string]$repoRoot) {
    # D-14. Order: -ApiToken > $env:ORCH_API_TOKEN > <repoRoot>\.env.
    if ($explicit) { return @{ token = $explicit; source = 'parameter' } }
    if ($env:ORCH_API_TOKEN) { return @{ token = $env:ORCH_API_TOKEN; source = 'environment' } }
    $envFile = Join-Path $repoRoot '.env'
    if (Test-Path -LiteralPath $envFile) {
        try {
            # [IO.File]::ReadAllText, NOT Get-Content: PS 5.1's text cmdlets re-encode and mangle
            # non-ASCII, and the repo has been bitten by that on this very file. Read raw, split by hand.
            foreach ($line in ([System.IO.File]::ReadAllText($envFile, [System.Text.Encoding]::UTF8) -split "`r?`n")) {
                $t = $line.Trim()
                if ($t -and -not $t.StartsWith('#') -and $t -match '^ORCH_API_TOKEN\s*=\s*(.*)$') {
                    $v = $Matches[1].Trim()
                    # strip an inline comment the same way the container-side loader does
                    if ($v -match '^(.*?)\s+#') { $v = $Matches[1].Trim() }
                    # ...and strip ONE matched pair of surrounding quotes, because docker compose does.
                    # This is not cosmetic. `ORCH_API_TOKEN="abc"` is the conventional .env style (and is
                    # REQUIRED when the value contains a space or '#'). Compose resolves it to `abc`;
                    # without this the bridge would send `"abc"` and 401 — and the FATAL message below
                    # would tell the operator "your token does not match, compare them" while the two
                    # values look IDENTICAL in every place they can inspect. An unfalsifiable diagnosis
                    # is worse than no diagnosis. Verified against `docker compose config`.
                    if ($v.Length -ge 2 -and (($v[0] -eq '"' -and $v[-1] -eq '"') -or `
                                              ($v[0] -eq "'" -and $v[-1] -eq "'"))) {
                        $v = $v.Substring(1, $v.Length - 2)
                    }
                    if ($v) { return @{ token = $v; source = '.env' } }
                }
            }
        } catch {
            Write-Warning "could not read ORCH_API_TOKEN from ${envFile}: $($_.Exception.Message)"
        }
    }
    return @{ token = ''; source = 'none' }
}

function Invoke-IngestPost([string]$url, $payloadObj) {
    $json = $payloadObj | ConvertTo-Json -Depth 8 -Compress
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    $headers = @{}
    # D-14: the header is added ONLY when a token exists. Sending 'Bearer ' with an empty value against
    # an auth-disabled dev orchestrator would be a behaviour change for the default setup.
    if ($script:ApiTokenResolved) { $headers['Authorization'] = "Bearer $script:ApiTokenResolved" }
    return Invoke-RestMethod -Uri $url -Method Post -Body $bytes -Headers $headers `
        -ContentType 'application/json; charset=utf-8' -TimeoutSec 90
}

function Get-HttpStatus($errorRecord) {
    # PS 5.1: a non-2xx makes Invoke-RestMethod THROW; the code lives on the inner WebException response.
    try {
        $r = $errorRecord.Exception.Response
        if ($r -and $r.StatusCode) { return [int]$r.StatusCode }
    } catch {}
    return 0
}

function Get-InboxFolders($inbox, [string[]]$wanted, [bool]$recurse) {
    # Explicit UI names select only those direct Inbox children. -Subfolders remains the CLI all-children override.
    $folders = @()
    if ($recurse -or @($wanted | Where-Object { $_ -ieq 'Inbox' }).Count) { $folders += $inbox }
    if ($recurse) {
        foreach ($f in $inbox.Folders) {
            try { $folders += $f } catch {}
        }
    } else {
        foreach ($f in $inbox.Folders) {
            try { if (@($wanted | Where-Object { $_ -ieq $f.Name }).Count) { $folders += $f } } catch {}
        }
    }
    return $folders
}

function Resolve-OutlookTargets($Namespace, [string[]]$RequestedAccounts) {
    # Fail before creating a batch: a typo or an inaccessible account must not look like an empty inbox.
    $targets = @()
    foreach ($requested in ($RequestedAccounts | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($requested)) { throw 'A requested mailbox address is empty.' }
        $matches = @($Namespace.Accounts | Where-Object { $_.SmtpAddress -ieq $requested.Trim() })
        if ($matches.Count -ne 1) {
            throw "Mailbox '$requested' must match exactly one Outlook account (found $($matches.Count))."
        }
        try { $inbox = $matches[0].DeliveryStore.GetDefaultFolder($OL_FOLDER_INBOX) }
        catch { throw "Cannot open Inbox for mailbox '$requested': $($_.Exception.Message)" }
        if (-not $inbox) { throw "Cannot open Inbox for mailbox '$requested'." }
        $targets += [pscustomobject]@{ smtp = [string]$matches[0].SmtpAddress; inbox = $inbox }
    }
    return $targets
}

# ---------------------------------------------------------------- setup
$nasOk = (-not $CountOnly) -and (-not $NoArchive) -and (-not [string]::IsNullOrWhiteSpace($NasRoot)) -and (Test-Path -LiteralPath $NasRoot)
if ((-not $CountOnly) -and (-not $NoArchive) -and $NasRoot -and (-not $nasOk)) {
    Write-Warning "NAS root '$NasRoot' not reachable - raw-email archive DISABLED for this run (ingest continues)."
}

$dateFrom = if ($PeriodMode -eq 'interval' -and $ReceivedFrom) { [datetime]::Parse($ReceivedFrom) } else { $null }
$dateTo = if ($PeriodMode -eq 'interval' -and $ReceivedTo) { [datetime]::Parse($ReceivedTo) } else { $null }
if ($PeriodMode -eq 'interval' -and (-not $dateFrom -or -not $dateTo)) { throw 'Interval mode requires ReceivedFrom and ReceivedTo.' }
if ($dateFrom -and $dateTo -and $dateFrom -gt $dateTo) { throw 'ReceivedFrom must be before ReceivedTo' }
if ($SinceDays -lt 1 -or $MaxItems -lt 0) { throw 'SinceDays must be positive and MaxItems must not be negative.' }
$cutoff = if ($PeriodMode -eq 'interval' -and $dateFrom) { $dateFrom } else { (Get-Date).AddDays(-$SinceDays) }
$seen = Load-Seen
$azureSeen = Load-Seen $AZURE_SEEN_FILE
$retry = Load-RetryCounts   # s27/CH3: per-EntryID save-retry counts (persisted across runs)
Write-Host ("=== outlook_bridge :: DryRun={0} AllEmails={1} window={2:s}..{3} MaxItems={4} seen={5} ===" -f `
    [bool]$DryRun, [bool]$AllEmails, $cutoff, $(if ($dateTo) { $dateTo.ToString('s') } else { 'now' }), $MaxItems, $seen.Count) -ForegroundColor Cyan

# D-14: resolve the inbound token ONCE, and SAY which source it came from. Before this the bridge sent no
# Authorization header at all, so any deployment with ORCH_API_TOKEN set (mandatory under APP_PROFILE=prod)
# rejected every POST with 401 and the whole email channel was dead. Printing the source is what turns a
# silent misconfiguration ("I set it in .env, why 401?") into a one-line diagnosis.
$tokenInfo = if ($CountOnly) { @{ token = ''; source = 'count-only' } } else { Resolve-ApiToken $ApiToken $RepoRoot }
$script:ApiTokenResolved = $tokenInfo.token
$script:LastHttpStatus = $null
if ($script:ApiTokenResolved) {
    Write-Host ("auth: Bearer token from {0} (len={1})" -f $tokenInfo.source, $script:ApiTokenResolved.Length) -ForegroundColor Cyan
} else {
    # ASCII-only INSIDE string literals in this file. A comment may carry an em dash (several already do)
    # because a comment runs to end-of-line, but a non-ASCII byte inside a STRING is a parse hazard: read
    # under the ANSI codepage, UTF-8 'em dash' (E2 80 94) ends in 0x94 = U+201D, which PowerShell accepts
    # as a closing string delimiter. The string terminates early and the rest of the line becomes code.
    # Measured: this exact line made Parser::ParseFile report "Missing closing '}'" 170 lines earlier.
    Write-Host "auth: NO token (dev parity - correct only while the orchestrator's ORCH_API_TOKEN is unset)" -ForegroundColor DarkYellow
}

# Outlook is acquired and every requested Inbox is checked before the first write.
if ($ExistingOutlook) {
    $currentSession = (Get-Process -Id $PID).SessionId
    $runningOutlook = @(Get-Process OUTLOOK -ErrorAction SilentlyContinue | Where-Object { $_.SessionId -eq $currentSession })
    if ($runningOutlook.Count -eq 0) { throw 'Outlook must already be running in the current interactive session.' }
}
$ol = New-Object -ComObject Outlook.Application
$ns = $ol.GetNamespace('MAPI')
try {
$targets = @(Resolve-OutlookTargets $ns $Accounts)
if (-not $CountOnly) {
    foreach ($d in @($DATA_DIR, $TMP_DIR)) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
}

# One durable scope per bridge run. Every email posted below carries this batch_id, so its child document
# runs and later reports stay together instead of mixing with the whole historical mailbox corpus.
$script:EmailBatchId = $null
$script:RequestedWorkflowHash = $WorkflowHash
$script:WorkflowCompatibleHashes = @()
$script:WorkflowActiveHash = ''
if (-not $DryRun -and -not $CountOnly) {
    $baseUrl = $OrchUrl -replace '/ingest/email/?$', ''
    $batchPayload = @{ name = ('Email {0:yyyy-MM-dd HH:mm}' -f (Get-Date)); source_kind = 'email'; expected_items = 0;
                       workflow_id = $WorkflowId; workflow_version = $WorkflowVersion;
                       source_config = @{ workflow_requested_hash=$WorkflowHash; external_key = ('email-run:' + [guid]::NewGuid().ToString('N')); accounts = $Accounts;
                                          folders = $MailFolders; period_mode = $PeriodMode;
                                          received_from = $ReceivedFrom; received_to = $ReceivedTo; since_days = $SinceDays; ocr_policy = $OcrPolicy } } | ConvertTo-Json -Depth 5
    $headers = @{ 'Content-Type'='application/json'; 'X-Actor'='outlook-bridge' }
    if ($script:ApiTokenResolved) { $headers.Authorization = "Bearer $($script:ApiTokenResolved)" }
    $batchResponse = Invoke-RestMethod -Uri "$baseUrl/api/intake-batches" -Method Post -Headers $headers -Body ([Text.Encoding]::UTF8.GetBytes($batchPayload))
    if ($batchResponse.PSObject.Properties.Name -contains 'workflow_compatible_hashes') {
        $script:WorkflowCompatibleHashes = @($batchResponse.workflow_compatible_hashes)
    }
    if (-not $batchResponse.id -or $batchResponse.workflow_id -ne $WorkflowId -or [int]$batchResponse.workflow_version -ne $WorkflowVersion -or
        -not $batchResponse.workflow_hash -or ($WorkflowHash -and $batchResponse.workflow_hash -ne $WorkflowHash -and $script:WorkflowCompatibleHashes -notcontains $WorkflowHash)) {
        throw 'The server did not confirm the requested workflow definition; no emails were posted.'
    }
    $WorkflowHash = [string]$batchResponse.workflow_hash
    if ($batchResponse.PSObject.Properties.Name -contains 'workflow_active_hash') { $script:WorkflowActiveHash = [string]$batchResponse.workflow_active_hash }
    $script:EmailBatchId = $batchResponse.id
}

$grand = [ordered]@{ scanned = 0; mail = 0; withDocs = 0; attachments = 0; posted = 0; deduped = 0; skippedSeen = 0; noDoc = 0; attachFail = 0; errors = 0 }
$accountCounts = @()
$processed = 0
$stop = $false

foreach ($target in $targets) {
    if ($stop) { break }
    $smtp = $target.smtp
    $acctSafe = Get-SafeName $smtp 60
    $inbox = $target.inbox
    $per = [ordered]@{ scanned = 0; mail = 0; withDocs = 0; attachments = 0; posted = 0; deduped = 0; skippedSeen = 0; noDoc = 0; attachFail = 0; errors = 0 }
    Write-Host ("--- account {0} ---" -f $smtp) -ForegroundColor Yellow

    foreach ($folder in (Get-InboxFolders $inbox $MailFolders ([bool]$Subfolders))) {
        if ($stop) { break }
        $items = $folder.Items
        # The lower-bound early break is correct only after a successful newest-first sort.
        $items.Sort('[ReceivedTime]', $true)
        $count = $items.Count

        for ($i = 1; $i -le $count; $i++) {
            if ($stop) { break }
            $item = $null
            try { $item = $items.Item($i) } catch { $per.errors++; $grand.errors++; continue }
            try {
                if ($item.Class -ne $OL_MAIL_CLASS) { continue }
                $per.scanned++; $grand.scanned++
                $rt = $null; try { $rt = $item.ReceivedTime } catch {}
                if ($rt -isnot [datetime]) { throw 'Email ReceivedTime is unavailable; refusing an unbounded item.' }
                if ($rt -and $dateTo -and ($rt -gt $dateTo)) { continue }
                if ($rt -and ($rt -lt $cutoff)) { break }          # sorted desc -> everything past here is older
                $per.mail++; $grand.mail++

                $entryId = $item.EntryID
                $policySeen = if ($OcrPolicy -eq 'azure') { $azureSeen.Contains($entryId) } else { $seen.Contains($entryId) -or $azureSeen.Contains($entryId) }
                if ((-not $Force) -and $policySeen) { $per.skippedSeen++; $grand.skippedSeen++; continue }

                # ---- gather qualifying document attachments
                $docAtts = @()
                $mailAttachments = $item.Attachments
                if ($null -eq $mailAttachments) { throw 'Email attachments are unavailable; refusing an incomplete item.' }
                foreach ($att in $mailAttachments) { if (Test-DocAttachment $att) { $docAtts += $att } }
                if (($docAtts.Count -eq 0) -and (-not $AllEmails)) { $per.noDoc++; $grand.noDoc++; continue }
                if ($docAtts.Count -gt 0) { $per.withDocs++; $grand.withDocs++ }
                $per.attachments += $docAtts.Count; $grand.attachments += $docAtts.Count
                if ($CountOnly) {
                    $processed++
                    if ($MaxItems -gt 0 -and $processed -ge $MaxItems) { $stop = $true }
                    continue
                }

                $eidShort = Get-ShortHash $entryId 16
                $subject = ''; try { $subject = [string]$item.Subject } catch {}
                $senderName = ''; try { $senderName = [string]$item.SenderName } catch {}
                $senderSmtp = Get-SenderSmtp $item
                $toList = @(Get-RecipientsSmtp $item 1)   # olTo
                $ccList = @(Get-RecipientsSmtp $item 2)   # olCC
                $bodyPreview = ''; try { $b = [string]$item.Body; if ($b.Length -gt $BODY_PREVIEW_CHARS) { $b = $b.Substring(0, $BODY_PREVIEW_CHARS) }; $bodyPreview = $b } catch {}
                $receivedIso = ''; if ($rt) { $receivedIso = $rt.ToString('yyyy-MM-ddTHH:mm:ss') }

                # ---- drop attachments under host data/ (sidecar path contract: /data/...)
                $hostDir = Join-Path $DATA_DIR ("inbox\email\{0}\{1}" -f $acctSafe, $eidShort)
                if (-not (Test-Path $hostDir)) { New-Item -ItemType Directory -Path $hostDir -Force | Out-Null }
                $attachmentsPayload = @()
                $savedFiles = @()
                $n = 0
                foreach ($att in $docAtts) {
                    $n++
                    $safeFn = Get-SafeName ([string]$att.FileName) 90
                    if (-not [System.IO.Path]::GetExtension($safeFn)) { $safeFn = "$safeFn.pdf" }
                    $safeFn = ("{0:d2}_{1}" -f $n, $safeFn)
                    $hostFile = Join-Path $hostDir $safeFn
                    try {
                        $att.SaveAsFile($hostFile)
                        $savedFiles += $hostFile
                        $containerPath = "/data/inbox/email/$acctSafe/$eidShort/$safeFn"
                        $attachmentsPayload += @{ path = $containerPath; filename = [string]$att.FileName }
                    } catch { Write-Warning "    attach save failed ($($att.FileName)): $($_.Exception.Message)" }
                }

                # s27/CH3: recognized (qualifying) vs actually-saved. A positive gap is silent attachment
                # loss (a SaveAsFile failure above); we must NOT mark the email seen while save-retries remain
                # (else the seen-set skips it next run and the missing attachment is lost forever).
                $recognized = @($docAtts).Count
                $saved = @($savedFiles).Count
                $failed = $recognized - $saved

                # ---- raw-email archive to NAS (.msg + doc attachments)
                if ($nasOk) {
                    try {
                        $ym = if ($rt) { $rt.ToString('yyyy-MM') } else { 'unknown' }
                        $arcDir = Join-Path $NasRoot ("raw\{0}\{1}\{2}" -f $acctSafe, $ym, $eidShort)
                        if (-not (Test-Path $arcDir)) { New-Item -ItemType Directory -Path $arcDir -Force | Out-Null }
                        $item.SaveAs((Join-Path $arcDir 'message.msg'), $OL_SAVE_MSG_UNICODE)
                        foreach ($sf in $savedFiles) { Copy-Item -Path $sf -Destination $arcDir -Force }
                    } catch { Write-Warning "    NAS archive failed: $($_.Exception.Message)" }
                }

                # ---- build the /ingest/email payload
                $payload = [ordered]@{
                    batch_id    = $script:EmailBatchId
                    message_id   = $entryId
                    account      = $smtp
                    from         = $senderSmtp
                    sender       = $senderName
                    to           = $toList
                    cc           = $ccList
                    subject      = $subject
                    body_preview = $bodyPreview
                    received     = $receivedIso
                    attachments  = $attachmentsPayload
                    ocr_policy   = $OcrPolicy
                    attachments_failed = $failed         # s27/CH3: recognized-but-unsaved (server records the loss)
                    n_recognized       = $recognized      # s27/CH3
                    force        = [bool]$Force   # s26: -Force now also re-processes server-side (bypasses the
                }                                  # bare.ingest_cursor dedup), not just the local seen-set.

                $processed++
                $subjShort = $subject
                if ($subjShort.Length -gt 70) { $subjShort = $subjShort.Substring(0, 70) }
                $nDocs = $attachmentsPayload.Count
                if ($DryRun) {
                    Write-Host "  [DRY] $receivedIso | docs=$nDocs | $subjShort" -ForegroundColor DarkGray
                    foreach ($ap in $attachmentsPayload) { Write-Host "        -> $($ap.path)" -ForegroundColor DarkGray }
                }
                elseif (($failed -gt 0) -and ((([int]$retry[$entryId]) + 1) -lt $MaxAttachRetries)) {
                    # s27/CH3: partial save + retries remain -> DO NOT post, DO NOT mark seen. Re-attempt the
                    # save next run (a SaveAsFile failure is often transient: a locked / still-streaming
                    # attachment). POST-once keeps the server dedup clean (no forced re-ingest, no LLM
                    # double-spend) — the eventual complete run is the FIRST post for this message_id.
                    $attempts = ([int]$retry[$entryId]) + 1
                    Add-Retry $entryId; $retry[$entryId] = $attempts
                    $per.attachFail++; $grand.attachFail++
                    Write-Ledger @{ ts = $receivedIso; account = $smtp; entry_id = $entryId; run_id = $null; deduped = $false; n_attachments = $saved; n_recognized = $recognized; attachments_failed = $failed; attempts = $attempts; retry_pending = $true; subject = $subject }
                    Write-Warning "  [RETRY] $receivedIso | saved $saved/$recognized attachments (attempt $attempts/$MaxAttachRetries) -> NOT marked seen | $subjShort"
                }
                else {
                    # Complete save ($failed -eq 0), OR partial with save-retries EXHAUSTED -> post whatever
                    # saved and give up on the rest (mark seen so it stops retrying; the raw email is
                    # NAS-archived for a manual recover). ALWAYS post here: a complete email may legitimately
                    # have ZERO attachments (-AllEmails ingests body-only emails for intent/tag-cloud), and an
                    # exhausted give-up posts its (partial/empty) set WITH attachments_failed>0 so the loss is
                    # recorded server-side (py signal), not only in the local ledger.
                    $exhausted = ($failed -gt 0)
                    try {
                        $resp = Invoke-IngestPost $OrchUrl $payload
                        if ($OcrPolicy -eq 'azure' -and $resp.ocr_policy -ne 'azure') {
                            throw 'The server did not confirm the requested Azure OCR policy; the message remains eligible for retry.'
                        }
                        $rid = $null; $ded = $false
                        try { $rid = $resp.run_id } catch {}
                        try { $ded = [bool]$resp.deduped } catch {}
                        if ($ded) { $per.deduped++; $grand.deduped++ } else { $per.posted++; $grand.posted++ }
                        Add-Seen $entryId; [void]$seen.Add($entryId)
                        if ($resp.ocr_policy -eq 'azure') { Add-Seen $entryId $AZURE_SEEN_FILE; [void]$azureSeen.Add($entryId) }
                        if ($exhausted) { $per.attachFail++; $grand.attachFail++ }
                        Write-Ledger @{ ts = $receivedIso; account = $smtp; entry_id = $entryId; run_id = $rid; deduped = $ded; n_attachments = $saved; n_recognized = $recognized; attachments_failed = $failed; attempts = ([int]$retry[$entryId]); retry_exhausted = $exhausted; subject = $subject; ocr_policy = $OcrPolicy }
                        $dedTag = ''; if ($ded) { $dedTag = ' (dedup)' }
                        if ($exhausted) { Write-Warning "  [GAVEUP] $receivedIso | saved $saved/$recognized, $failed lost after $MaxAttachRetries retries | run_id=$rid$dedTag | $subjShort" }
                        else { Write-Host "  [OK ] $receivedIso | docs=$saved | run_id=$rid$dedTag | $subjShort" -ForegroundColor Green }
                    } catch {
                        $per.errors++; $grand.errors++
                        $code = Get-HttpStatus $_
                        $script:LastHttpStatus = $code
                        Write-Warning "  POST failed for '$subject' (HTTP $code): $($_.Exception.Message)"
                        # D-14: 401/403 is a CONFIGURATION fault, not a transient one — every remaining
                        # email in this run will fail identically. Continuing would bury the cause under
                        # hundreds of identical warnings and waste a full mailbox scan. Stop loudly, with
                        # the exact remedy. (Nothing is lost: a failed POST never marks the mail seen, so
                        # the next run re-processes it.)
                        if ($code -eq 401 -or $code -eq 403) {
                            Write-Host ""
                            Write-Host "FATAL: the orchestrator rejected our credentials (HTTP $code)." -ForegroundColor Red
                            if ($script:ApiTokenResolved) {
                                Write-Host ("  A token WAS sent (from {0}, len={1}) but was not accepted." -f `
                                    $tokenInfo.source, $script:ApiTokenResolved.Length) -ForegroundColor Red
                                Write-Host "  -> it does not match the orchestrator's ORCH_API_TOKEN. Compare them." -ForegroundColor Red
                            } else {
                                Write-Host "  NO token was sent, but the orchestrator requires one." -ForegroundColor Red
                                Write-Host "  -> set ORCH_API_TOKEN in $RepoRoot\.env, or pass -ApiToken." -ForegroundColor Red
                            }
                            Write-Host "  Nothing was marked seen; the next run re-processes these emails." -ForegroundColor Red
                            Write-Host ""
                            $stop = $true
                        }
                    }
                }

                if (($MaxItems -gt 0) -and ($processed -ge $MaxItems)) { Write-Host "  reached MaxItems=$MaxItems -> stopping." -ForegroundColor Cyan; $stop = $true }
            }
            catch {
                $per.errors++; $grand.errors++
                Write-Warning "  item error @L$($_.InvocationInfo.ScriptLineNumber): $($_.Exception.Message)"
            }
            finally { if ($item -and [Runtime.InteropServices.Marshal]::IsComObject($item)) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($item) } }
        }
    }
    Write-Host ("  [{0}] scanned={1} mail={2} withDocs={3} posted={4} deduped={5} skippedSeen={6} noDoc={7} attachFail={8} errors={9}" -f `
            $smtp, $per.scanned, $per.mail, $per.withDocs, $per.posted, $per.deduped, $per.skippedSeen, $per.noDoc, $per.attachFail, $per.errors) -ForegroundColor Yellow
    $accountCounts += [pscustomobject]@{ account = $smtp; counts = $per }
}

Write-Host ("=== TOTAL :: processed={0} | posted={1} deduped={2} withDocs={3} skippedSeen={4} noDoc={5} mail={6} scanned={7} attachFail={8} errors={9} ===" -f `
        $processed, $grand.posted, $grand.deduped, $grand.withDocs, $grand.skippedSeen, $grand.noDoc, $grand.mail, $grand.scanned, $grand.attachFail, $grand.errors) -ForegroundColor Cyan
if ($CountOnly) {
    if ($grand.errors -gt 0) { throw "Email count failed with $($grand.errors) error(s)." }
    [pscustomobject]@{ count_only = $true; received_from = $cutoff.ToString('s');
        received_to = $(if ($dateTo) { $dateTo.ToString('s') } else { $null });
        eligible = $processed; counts = $grand; accounts = $accountCounts }
    return
}
if (-not $DryRun) { Write-Host "Ledger: $LEDGER_FILE" -ForegroundColor Cyan }
if ((-not $DryRun) -and $script:EmailBatchId) {
    try {
        $baseUrl = $OrchUrl -replace '/ingest/email/?$', ''
        $headers = @{ 'X-Actor'='outlook-bridge' }
        if ($script:ApiTokenResolved) { $headers.Authorization = "Bearer $($script:ApiTokenResolved)" }
        Invoke-RestMethod -Uri "$baseUrl/api/intake-batches/$($script:EmailBatchId)/seal" -Method Post -Headers $headers | Out-Null
    } catch { $grand.errors++; Write-Warning "could not seal email batch $($script:EmailBatchId): $($_.Exception.Message)" }
}

# ---------------------------------------------------------------- Ü7.4/CH1: the host<->container status bridge
# The orchestrator cannot see this script (Outlook COM lives on the host), so if the scheduled task stops
# firing — host asleep, schtasks disabled, broken Outlook profile — email intake silently goes to ZERO and
# every downstream surface just looks quiet. Writing a heartbeat here lets /health surface it (passive) and
# the daily email-ingest-check cron alert on staleness (active). Mirrors backup.ps1's backup-status.json.
#
# Written only at the END of a real run, so the file's timestamp means "a poll cycle COMPLETED". A crash
# before this point writes nothing, ages the file out, and trips the same staleness alarm — the failure mode
# that most needs catching therefore needs no cooperation from the failing script.
# COUNTERS + TIMESTAMPS ONLY: no subject, sender, or path (it crosses the host boundary in cleartext).
if (-not $DryRun) {
    $statusFile = Join-Path $DATA_DIR 'email-bridge-status.json'
    try {
        $status = [ordered]@{
            last_run = (Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ')
            status   = $(if ($grand.errors -gt 0 -or $grand.attachFail -gt 0) { 'error' } else { 'ok' })
            posted   = $grand.posted
            deduped  = $grand.deduped
            errors   = $grand.errors
            attach_failed = $grand.attachFail
            scanned  = $grand.scanned
            accounts = $Accounts.Count
            ocr_policy = $OcrPolicy
            workflow_id = $WorkflowId
            workflow_version = $WorkflowVersion
            workflow_hash = $WorkflowHash
            workflow_requested_hash = $script:RequestedWorkflowHash
            workflow_active_hash = $script:WorkflowActiveHash
            workflow_compatible_hashes = $script:WorkflowCompatibleHashes
            host     = $env:COMPUTERNAME
            # D-14: the heartbeat previously said only "error" — true but useless. An operator seeing
            # `auth_mode: none` + `last_http_status: 401` knows the cause without opening a log on a host
            # the orchestrator cannot reach. Counters + status codes only, no PII (the file crosses the
            # host boundary in cleartext).
            last_http_status = $script:LastHttpStatus
            auth_mode = $(if ($script:ApiTokenResolved) { $tokenInfo.source } else { 'none' })
        }
        # UTF-8 WITHOUT BOM ([IO.File]::WriteAllText default) so the container's json.load reads it clean
        # (the reader tolerates a BOM anyway — belt and braces against the PS 5.1 encoding trap).
        [IO.File]::WriteAllText($statusFile, ($status | ConvertTo-Json -Depth 3))
        Write-Host "Status: $statusFile" -ForegroundColor Cyan
    } catch {
        # A status-write failure must never fail an otherwise-good ingest run: the consequence is a stale
        # heartbeat, which the dead-man cron reports anyway.
        Write-Warning "could not write email-bridge-status.json: $($_.Exception.Message)"
    }
}
if ($grand.errors -gt 0 -or $grand.attachFail -gt 0) {
    throw "Email intake finished with $($grand.errors) error(s) and $($grand.attachFail) attachment failure(s)."
}
} finally {
    foreach ($com in @($ns, $ol)) {
        if ($com -and [Runtime.InteropServices.Marshal]::IsComObject($com)) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($com) }
    }
}
