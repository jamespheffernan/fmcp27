# Run a program on the logged-on user's desktop from an SSH session, through a scheduled task.
#   powershell -File on_desktop.ps1 -Execute <program> [-Argument <arguments>]
param([Parameter(Mandatory)] [string] $Execute, [string] $Argument = '')
$ErrorActionPreference = 'Stop'
$action = if ($Argument) { New-ScheduledTaskAction -Execute $Execute -Argument $Argument } else { New-ScheduledTaskAction -Execute $Execute }
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName 'fmcp-desktop' -Action $action -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName 'fmcp-desktop'
Write-Output "started on the desktop: $Execute $Argument"
