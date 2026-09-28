<#
.SYNOPSIS
  Installs the Tally Analytics Sync Agent as a Windows service (D-042 #3, D-043 #3).
  Run from the unzipped TallyAgent folder, in an elevated Windows PowerShell:
    powershell -ExecutionPolicy Bypass -File .\Install-TallyAgent.ps1
#>
#Requires -RunAsAdministrator
param(
    [string]$InstallDir = "$env:ProgramFiles\TallyAgent",
    [string]$DataDir = "$env:ProgramData\TallyAgent"
)
$ErrorActionPreference = "Stop"
$Service = "TallyAgent"
$Account = "NT SERVICE\$Service"   # a virtual account: low-privilege, not LocalSystem

if (Get-Service -Name $Service -ErrorAction SilentlyContinue) {
    throw "The service $Service is already installed. Run Uninstall-TallyAgent.ps1 first."
}

Write-Host "Copying the Agent to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item -Recurse -Force -Path (Join-Path $PSScriptRoot "*") -Destination $InstallDir

Write-Host "Creating the service $Service (runs as $Account, starts with Windows)"
$exe = Join-Path $InstallDir "tally-agent-service.exe"
& sc.exe create $Service binPath= "`"$exe`"" obj= $Account start= delayed-auto DisplayName= "Tally Analytics Sync Agent" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "sc.exe create failed ($LASTEXITCODE)" }
& sc.exe description $Service "Reads TallyPrime (read-only) and uploads to Tally Analytics over HTTPS." | Out-Null
& sc.exe failure $Service reset= 86400 actions= restart/60000/restart/60000/restart/300000 | Out-Null

Write-Host "Restricting $DataDir to the service account, SYSTEM and Administrators (AGT-2.6)"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
& icacls $DataDir /inheritance:r /grant:r "${Account}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "icacls failed ($LASTEXITCODE)" }

Write-Host ""
Write-Host "Installed. Next, in this elevated window:"
Write-Host "  1. `"$InstallDir\tally-agent.exe`" register --token <token> --name <name> --backend-url <https://...> --company `"<Tally company>`""
Write-Host "     (add --ca-bundle <file> and --proxy-url <url> if your network needs them)"
Write-Host "  2. sc.exe start $Service"
Write-Host "Details: $InstallDir\agent-install.md"
