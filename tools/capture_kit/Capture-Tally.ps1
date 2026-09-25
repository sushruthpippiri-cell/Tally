<#
.SYNOPSIS
    Capture TallyPrime XML responses as evidence for the live-Tally validation gate (D-038).

.DESCRIPTION
    Uses only what ships with Windows (Windows PowerShell 5.1 and .NET). Nothing to install.
    Sends each request in manifest.json to TallyPrime's XML server and saves the request, the
    response exactly as received (raw bytes) and a .meta.json per request, then zips the run.
    A request that fails is saved with its error and the run continues with the next one.

    USE A DEDICATED TEST COMPANY ONLY - NEVER A REAL BUSINESS'S BOOKS.
    The captured responses are committed to the project's repository.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step check -Company "Tally Test Co"
    powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step all -Company "Tally Test Co" -OtherCompany "Second Test Co"
    powershell -ExecutionPolicy Bypass -File .\Capture-Tally.ps1 -Step scenario -Name G8 -Company "Tally Test Co"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('check', 'capture', 'reference', 'scenario', 'all')]
    [string]$Step,
    [Parameter(Mandatory = $true)]
    [string]$Company,
    [string]$OtherCompany = '',
    [string]$Name = '',
    [string]$OutDir = '',
    [string]$TallyHost = 'localhost',
    [int]$Port = 9000,
    [string]$BooksFrom = '20240401',
    [string]$AsOf = '20250331',
    [int]$TimeoutMinutes = 15,
    [switch]$NonInteractive
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$KitDir = $PSScriptRoot
if (-not $OutDir) { $OutDir = Join-Path $KitDir 'captures' }
$Utf8 = New-Object System.Text.UTF8Encoding($false)
$Manifest = [IO.File]::ReadAllText((Join-Path $KitDir 'manifest.json'), $Utf8) | ConvertFrom-Json
$BaseUrl = "http://${TallyHost}:${Port}/"
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$RunName = if ($Step -eq 'scenario') { "$Stamp-scenario-$Name" } else { "$Stamp-$Step" }
$RunDir = Join-Path $OutDir $RunName
$Summary = New-Object System.Collections.ArrayList

function Write-Banner {
    Write-Host ''
    Write-Host '==========================================================================' -ForegroundColor Yellow
    Write-Host '  TEST COMPANY ONLY. Never run this against a real business''s books:' -ForegroundColor Yellow
    Write-Host '  every response captured here is committed to the project repository.' -ForegroundColor Yellow
    Write-Host '==========================================================================' -ForegroundColor Yellow
    Write-Host ''
}

function Get-XmlEscaped([string]$Value) {
    return [System.Security.SecurityElement]::Escape($Value)
}

function Expand-Template([string]$RelativePath, [string]$CompanyName) {
    $text = [IO.File]::ReadAllText((Join-Path $KitDir $RelativePath), $Utf8)
    $values = [ordered]@{
        '{{COMPANY}}'       = $CompanyName
        '{{OTHER_COMPANY}}' = $OtherCompany
        '{{BOOKS_FROM}}'    = $BooksFrom
        '{{AS_OF}}'         = $AsOf
    }
    foreach ($key in $values.Keys) {
        $text = $text.Replace($key, (Get-XmlEscaped $values[$key]))
    }
    return , $Utf8.GetBytes($text)
}

function ConvertTo-Text([byte[]]$Bytes) {
    if ($null -eq $Bytes -or $Bytes.Length -eq 0) { return '' }
    if ($Bytes.Length -ge 2 -and $Bytes[0] -eq 0xFF -and $Bytes[1] -eq 0xFE) {
        return [Text.Encoding]::Unicode.GetString($Bytes, 2, $Bytes.Length - 2)
    }
    if ($Bytes.Length -ge 4 -and $Bytes[1] -eq 0 -and $Bytes[3] -eq 0) {
        return [Text.Encoding]::Unicode.GetString($Bytes)
    }
    return $Utf8.GetString($Bytes)
}

function Get-TallyError([string]$Text) {
    if ($Text -match '<LINEERROR>(.*?)</LINEERROR>') { return $Matches[1] }
    return $null
}

function Invoke-Tally([byte[]]$Body, [string]$Method) {
    $result = [ordered]@{
        ok = $false; http_status = $null; elapsed_ms = 0; bytes = 0
        transport_error = $null; headers = [ordered]@{}; body = [byte[]]@()
    }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = $null
    try {
        $request = [System.Net.HttpWebRequest]::Create($BaseUrl)
        $request.Method = $Method
        $request.Timeout = $TimeoutMinutes * 60000
        $request.ReadWriteTimeout = $TimeoutMinutes * 60000
        if ($Method -eq 'POST') {
            $request.ContentType = $Manifest.content_type
            $request.ContentLength = $Body.Length
            $stream = $request.GetRequestStream()
            $stream.Write($Body, 0, $Body.Length)
            $stream.Close()
        }
        $response = $request.GetResponse()
    }
    catch [System.Net.WebException] {
        $result.transport_error = $_.Exception.Message
        $response = $_.Exception.Response
    }
    catch {
        $result.transport_error = $_.Exception.Message
    }
    if ($null -ne $response) {
        try {
            $result.http_status = [int]$response.StatusCode
            foreach ($header in $response.Headers.AllKeys) { $result.headers[$header] = $response.Headers[$header] }
            $buffer = New-Object IO.MemoryStream
            $response.GetResponseStream().CopyTo($buffer)
            $result.body = $buffer.ToArray()
            $result.bytes = $result.body.Length
            $result.ok = ($result.http_status -eq 200)
        }
        catch {
            $result.transport_error = $_.Exception.Message
        }
        finally {
            $response.Close()
        }
    }
    $result.elapsed_ms = $watch.ElapsedMilliseconds
    return $result
}

function Save-Capture([string]$Dir, [string]$Id, [object[]]$Gates, [byte[]]$RequestBytes, $Result) {
    New-Item -ItemType Directory -Force -Path $Dir | Out-Null
    if ($RequestBytes.Length -gt 0) {
        [IO.File]::WriteAllBytes((Join-Path $Dir "$Id.request.xml"), $RequestBytes)
    }
    if ($Result.bytes -gt 0) {
        [IO.File]::WriteAllBytes((Join-Path $Dir "$Id.response.xml"), $Result.body)
    }
    $text = ConvertTo-Text $Result.body
    $tallyError = Get-TallyError $text
    $meta = [ordered]@{
        id              = $Id
        gates           = $Gates
        url             = $BaseUrl
        http_status     = $Result.http_status
        ok              = ($Result.ok -and ($null -eq $tallyError))
        elapsed_ms      = $Result.elapsed_ms
        bytes           = $Result.bytes
        headers         = $Result.headers
        transport_error = $Result.transport_error
        tally_error     = $tallyError
        saved_at        = (Get-Date -Format 'o')
    }
    [IO.File]::WriteAllText((Join-Path $Dir "$Id.meta.json"), ($meta | ConvertTo-Json -Depth 6), $Utf8)
    return $meta
}

function Invoke-Entry($Entry, [string]$Dir, [string]$CompanyName, [int]$Index, [int]$Total) {
    $label = '[{0}/{1}] {2}' -f $Index, $Total, $Entry.id
    try {
        $bytes = Expand-Template $Entry.file $CompanyName
        $result = Invoke-Tally $bytes 'POST'
        $meta = Save-Capture $Dir $Entry.id $Entry.gates $bytes $result
    }
    catch {
        $meta = [ordered]@{ id = $Entry.id; gates = $Entry.gates; ok = $false; tally_error = $null
                            transport_error = $_.Exception.Message; bytes = 0; elapsed_ms = 0 }
        New-Item -ItemType Directory -Force -Path $Dir | Out-Null
        [IO.File]::WriteAllText((Join-Path $Dir "$($Entry.id).meta.json"), ($meta | ConvertTo-Json -Depth 6), $Utf8)
    }
    if ($meta.ok) {
        Write-Host ('{0,-40} OK      {1,10:N0} bytes  {2,6:N1} s' -f $label, $meta.bytes, ($meta.elapsed_ms / 1000))
    }
    else {
        $why = if ($meta.tally_error) { "Tally: $($meta.tally_error)" } else { "$($meta.transport_error)" }
        Write-Host ('{0,-40} FAILED  {1}' -f $label, $why) -ForegroundColor Red
    }
    [void]$Summary.Add($meta)
}

function Invoke-Entries([object[]]$Entries, [string]$Dir) {
    $todo = @($Entries | Where-Object { -not $_.needs_other_company -or $OtherCompany })
    $skipped = @($Entries | Where-Object { $_.needs_other_company -and -not $OtherCompany })
    foreach ($entry in $skipped) {
        Write-Host ("{0,-40} SKIPPED (give -OtherCompany to capture it)" -f $entry.id) -ForegroundColor DarkYellow
        [void]$Summary.Add([ordered]@{ id = $entry.id; gates = $entry.gates; ok = $false; skipped = $true })
    }
    $i = 0
    foreach ($entry in $todo) {
        $i += 1
        $companyName = if ($entry.needs_other_company) { $OtherCompany } else { $Company }
        Invoke-Entry $entry $Dir $companyName $i $todo.Count
    }
}

function Invoke-Check {
    Write-Host "Checking TallyPrime at $BaseUrl for company '$Company'"
    $dir = Join-Path $RunDir 'check'
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $check = [ordered]@{ tally_url = $BaseUrl; company = $Company; reachable = $false; server_running = $false
                         company_listed = $false; tdl_loaded = $false; company_open = $false
                         tdl_version = $null; tdl_version_expected = $Manifest.tdl_version; company_guid = $null; ok = $false }

    $tcp = New-Object System.Net.Sockets.TcpClient
    try { $check.reachable = $tcp.ConnectAsync($TallyHost, $Port).Wait(5000) -and $tcp.Connected } catch { $check.reachable = $false }
    finally { $tcp.Close() }
    if (-not $check.reachable) {
        Write-Host "1. XML server port $Port ... NOT REACHABLE" -ForegroundColor Red
        Write-Host "   Start TallyPrime and enable its XML server: F1 (Help) > Settings > Connectivity >"
        Write-Host "   'TallyPrime acts as' = Both (or Server), 'Port' = $Port. Restart TallyPrime." -ForegroundColor Yellow
    }
    else {
        Write-Host "1. XML server port $Port ... reachable" -ForegroundColor Green
        $root = Invoke-Tally ([byte[]]@()) 'GET'
        $rootMeta = Save-Capture $dir 'server_root' @('G35') ([byte[]]@()) $root
        $check.server_running = (ConvertTo-Text $root.body).Contains($Manifest.server_running_text)
        if ($check.server_running) { Write-Host '2. TallyPrime XML server answers ... yes' -ForegroundColor Green }
        else { Write-Host "2. TallyPrime XML server answers ... unexpected answer (saved in check\server_root.*)" -ForegroundColor Red }

        foreach ($entry in $Manifest.check) {
            $bytes = Expand-Template $entry.file $Company
            $result = Invoke-Tally $bytes 'POST'
            $meta = Save-Capture $dir $entry.id $entry.gates $bytes $result
            $text = ConvertTo-Text $result.body
            if ($entry.id -eq 'company_list') {
                $check.company_listed = $text.Contains((Get-XmlEscaped $Company)) -or $text.Contains($Company)
                if ($check.company_listed) { Write-Host "3. Company '$Company' is open ... yes" -ForegroundColor Green }
                else { Write-Host "3. Company '$Company' in TallyPrime's company list ... not found (step 4 decides)" -ForegroundColor Yellow }
            }
            else {
                $err = Get-TallyError $text
                $notFound = $false; foreach ($m in $Manifest.report_not_found_markers) { if ($text.Contains($m)) { $notFound = $true } }
                $notOpen = $false; foreach ($m in $Manifest.company_not_loaded_markers) { if ($text.Contains($m)) { $notOpen = $true } }
                if ($notFound) {
                    Write-Host '4. Project TDL (TA_Info report) ... NOT LOADED' -ForegroundColor Red
                    Write-Host '   Load TA_Minimal.tdl: README step 3. If TallyPrime showed an error while loading,' -ForegroundColor Yellow
                    Write-Host '   see README "Troubleshooting TDL errors" for exactly what to send back.' -ForegroundColor Yellow
                }
                elseif ($notOpen) {
                    $check.tdl_loaded = $true
                    Write-Host "4. Company '$Company' ... NOT OPEN in TallyPrime (TDL is loaded)" -ForegroundColor Red
                    Write-Host '   Open the company in TallyPrime (Alt+F3 / Select Company) and use its exact name.' -ForegroundColor Yellow
                }
                elseif ($text -match '<TDLVERSION>(.*?)</TDLVERSION>') {
                    $check.tdl_loaded = $true
                    $check.tdl_version = $Matches[1]
                    if ($text -match '<COMPANYGUID>(.*?)</COMPANYGUID>') { $check.company_guid = $Matches[1] }
                    $check.company_open = [bool]$check.company_guid
                    Write-Host "4. Project TDL ... loaded, version $($check.tdl_version) (kit expects $($Manifest.tdl_version))" -ForegroundColor Green
                    Write-Host "   Company GUID: $($check.company_guid)"
                }
                else {
                    $what = if ($err) { "Tally said: $err" } else { $meta.transport_error }
                    Write-Host "4. Project TDL (TA_Info report) ... REPORT FAILED: $what" -ForegroundColor Red
                }
            }
        }
    }
    $check.ok = $check.reachable -and $check.server_running -and $check.tdl_loaded -and $check.company_open
    [IO.File]::WriteAllText((Join-Path $RunDir 'check.json'), ($check | ConvertTo-Json -Depth 4), $Utf8)
    if ($check.ok) { Write-Host 'CHECK PASSED - ready to capture.' -ForegroundColor Green }
    else { Write-Host 'CHECK FAILED - fix the step marked above, then run -Step check again.' -ForegroundColor Red }
    return $check.ok
}

function Invoke-Scenario {
    $scenario = @($Manifest.scenarios | Where-Object { $_.name -eq $Name })
    if ($scenario.Count -ne 1) {
        $names = ($Manifest.scenarios | ForEach-Object { $_.name }) -join ', '
        throw "Unknown scenario '$Name'. Choose one of: $names"
    }
    $scenario = $scenario[0]
    $entries = @($Manifest.capture | Where-Object { $scenario.requests -contains $_.id })
    Write-Host "Scenario $($scenario.name): capturing BEFORE the change"
    Invoke-Entries $entries (Join-Path $RunDir 'before')
    Write-Host ''
    Write-Host 'NOW DO THIS IN TALLYPRIME:' -ForegroundColor Cyan
    foreach ($line in $scenario.instructions) { Write-Host "  $line" -ForegroundColor Cyan }
    $note = ''
    if (-not $NonInteractive) {
        $note = Read-Host 'Describe exactly what you changed (voucher number, old and new values), then press Enter'
    }
    [IO.File]::WriteAllText((Join-Path $RunDir 'scenario.json'),
        ([ordered]@{ name = $scenario.name; gates = $scenario.gates; instructions = $scenario.instructions; your_note = $note } | ConvertTo-Json -Depth 4), $Utf8)
    Write-Host "Scenario $($scenario.name): capturing AFTER the change"
    Invoke-Entries $entries (Join-Path $RunDir 'after')
    if ($scenario.undo) { Write-Host "Afterwards: $($scenario.undo)" -ForegroundColor Cyan }
}

# ---- main --------------------------------------------------------------------------------
Write-Banner
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null
$started = Get-Date -Format 'o'
$exitCode = 0

if ($Step -eq 'check' -or $Step -eq 'all') {
    if (-not (Invoke-Check)) { $exitCode = 1 }
}
if ($exitCode -eq 0 -and ($Step -eq 'capture' -or $Step -eq 'all')) {
    Write-Host 'Capturing every request in the manifest'
    Invoke-Entries @($Manifest.capture) (Join-Path $RunDir 'capture')
}
if ($exitCode -eq 0 -and ($Step -eq 'reference' -or $Step -eq 'all')) {
    Write-Host "Capturing TallyPrime's built-in reports as reference evidence (TEST-4.1)"
    Invoke-Entries @($Manifest.reference) (Join-Path $RunDir 'reference')
}
if ($Step -eq 'scenario') {
    Invoke-Scenario
}

$windows = $null
try {
    $os = Get-CimInstance Win32_OperatingSystem
    $windows = [ordered]@{ caption = $os.Caption; version = $os.Version; architecture = $os.OSArchitecture }
}
catch { }
$run = [ordered]@{
    kit_version            = $Manifest.kit_version
    tdl_version_expected   = $Manifest.tdl_version
    step                   = $Step
    scenario               = $Name
    company                = $Company
    other_company          = $OtherCompany
    books_from             = $BooksFrom
    as_of                  = $AsOf
    tally_url              = $BaseUrl
    started_at             = $started
    finished_at            = (Get-Date -Format 'o')
    windows                = $windows
    processor_architecture = $env:PROCESSOR_ARCHITECTURE
    powershell             = $PSVersionTable.PSVersion.ToString()
    tallyprime_version     = 'Write the TallyPrime version and build into CHECKLIST.md (F1 > About)'
}
[IO.File]::WriteAllText((Join-Path $RunDir 'run.json'), ($run | ConvertTo-Json -Depth 4), $Utf8)
[IO.File]::WriteAllText((Join-Path $RunDir 'summary.json'), (ConvertTo-Json -InputObject @($Summary) -Depth 6), $Utf8)

$failed = @($Summary | Where-Object { -not $_.ok -and -not ($_.Contains('skipped')) })
if ($failed.Count -gt 0) {
    Write-Host ''
    Write-Host "$($failed.Count) request(s) failed; they are saved with their errors (see summary.json):" -ForegroundColor Yellow
    foreach ($f in $failed) { Write-Host "  $($f.id)" -ForegroundColor Yellow }
}

Compress-Archive -Path $RunDir -DestinationPath "$RunDir.zip" -Force
Write-Host ''
Write-Host "Saved: $RunDir"
Write-Host "Zip:   $RunDir.zip  (copy this one file to the Mac if the folder is not shared)"
exit $exitCode
