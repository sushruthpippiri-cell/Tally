<#
.SYNOPSIS
  Removes the Tally Analytics Sync Agent service and program files (D-043 #4).
  The data folder (queue, logs, the encrypted credential) is left for inspection.
  Run in an elevated Windows PowerShell:
    powershell -ExecutionPolicy Bypass -File .\Uninstall-TallyAgent.ps1
#>
#Requires -RunAsAdministrator
param(
    [string]$InstallDir = "$env:ProgramFiles\TallyAgent",
    [string]$DataDir = "$env:ProgramData\TallyAgent"
)
$Service = "TallyAgent"
if (Get-Service -Name $Service -ErrorAction SilentlyContinue) {
    & sc.exe stop $Service | Out-Null
    Start-Sleep -Seconds 5
    & sc.exe delete $Service | Out-Null
    Write-Host "Removed the service $Service."
}
if (Test-Path $InstallDir) {
    Remove-Item -Recurse -Force $InstallDir
    Write-Host "Removed $InstallDir."
}
Write-Host ""
Write-Host "IMPORTANT: revoke this Agent in the dashboard now (Agents -> Revoke)."
Write-Host "Its encrypted credential is still in $DataDir; revoking it is what makes it useless."
Write-Host "Delete $DataDir yourself once you no longer need the queue or the logs."
