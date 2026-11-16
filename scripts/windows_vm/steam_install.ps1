# Queue a Steam game for download on the development machine without clicking through Steam.
#
#   powershell -File steam_install.ps1 -AppId 4530370 -InstallDir "Football Manager 27"
#
# Run over SSH while someone is logged on to the desktop with Steam signed in. Steam downloads
# any game that has an app manifest marked "update required" when it starts, so this writes that
# manifest and restarts Steam on the logged-on desktop. An SSH session cannot start a program on
# the desktop directly; a scheduled task that runs as the logged-on user can. No password is
# involved: Steam keeps its own sign-in.

param(
    [Parameter(Mandatory)] [int] $AppId,
    [Parameter(Mandatory)] [string] $InstallDir,
    [string] $Steam = 'C:\Program Files (x86)\Steam'
)

$ErrorActionPreference = 'Stop'
$exe = Join-Path $Steam 'steam.exe'
if (-not (Test-Path $exe)) { throw "Steam is not installed at $Steam" }

function Start-OnDesktop([string] $arguments) {
    # Runs steam.exe in the logged-on user's desktop session and returns at once.
    $action = if ($arguments) { New-ScheduledTaskAction -Execute $exe -Argument $arguments }
              else { New-ScheduledTaskAction -Execute $exe }
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Highest
    Register-ScheduledTask -TaskName 'fmcp-steam' -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName 'fmcp-steam'
}

$manifest = Join-Path $Steam "steamapps\appmanifest_$AppId.acf"
if (Test-Path $manifest) {
    Write-Output "manifest exists already: $manifest"
} else {
    if (Get-Process steam -ErrorAction SilentlyContinue) {
        Start-OnDesktop '-shutdown'
        foreach ($i in 1..30) { if (-not (Get-Process steam -ErrorAction SilentlyContinue)) { break }; Start-Sleep 1 }
        Get-Process steam, steamwebhelper -ErrorAction SilentlyContinue | Stop-Process -Force
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Steam 'steamapps') | Out-Null
    # StateFlags 1026 = update required + update started: Steam fetches the game when it starts.
    $text = "`"AppState`"`n{`n`t`"appid`"`t`t`"$AppId`"`n`t`"Universe`"`t`t`"1`"`n`t`"StateFlags`"`t`t`"1026`"`n" +
            "`t`"installdir`"`t`t`"$InstallDir`"`n}`n"
    [IO.File]::WriteAllText($manifest, $text, (New-Object Text.UTF8Encoding $false))
    Write-Output "wrote $manifest"
}

if (-not (Get-Process steam -ErrorAction SilentlyContinue)) {
    Start-OnDesktop ''
    foreach ($i in 1..30) { if (Get-Process steam -ErrorAction SilentlyContinue) { break }; Start-Sleep 1 }
}
if (Get-Process steam -ErrorAction SilentlyContinue) { Write-Output 'Steam is running' }
else { throw 'Steam did not start on the desktop (is someone logged on?)' }
