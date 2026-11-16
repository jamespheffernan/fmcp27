# First boot of the FMCP 27 Windows development machine (EC2, Windows Server 2022).
#
# vm.sh wraps this file in <powershell> tags, replaces __FMCP_PUBLIC_KEY__ with the Mac's public
# key and passes it as EC2 user data. It runs once, as SYSTEM, before anyone has logged on.
#
# It does only what later steps need to reach the machine and run the tests: OpenSSH with key
# login, Python 3.14, Git, the Zstandard library. The GPU driver, Steam and the game are separate steps run over SSH,
# where their output can be read. Progress goes to C:\fmcp\first_boot.log; the last line is
# "first boot complete" when every step ran.

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

New-Item -ItemType Directory -Force -Path C:\fmcp, C:\fmcp\downloads | Out-Null
$log = 'C:\fmcp\first_boot.log'
function Log($message) { "$(Get-Date -Format s) $message" | Add-Content -Path $log }

function Step($name, [scriptblock]$body) {
    Log "start: $name"
    try { & $body; Log "done: $name" }
    catch { Log "FAILED: ${name}: $($_.Exception.Message)"; $script:failed = $true }
}

$failed = $false

Step 'OpenSSH server' {
    $capability = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
    if ($capability.State -ne 'Installed') { Add-WindowsCapability -Online -Name $capability.Name | Out-Null }
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd

    # Administrators log in with the key in this file, not the per-user one.
    $keys = 'C:\ProgramData\ssh\administrators_authorized_keys'
    Set-Content -Path $keys -Value '__FMCP_PUBLIC_KEY__' -Encoding ascii
    icacls $keys /inheritance:r /grant 'Administrators:F' /grant 'SYSTEM:F' | Out-Null

    # Key login only; PowerShell as the shell an ssh command lands in.
    $config = 'C:\ProgramData\ssh\sshd_config'
    $text = Get-Content $config -Raw
    $text = $text -replace '(?m)^#?\s*PasswordAuthentication\s+\w+', 'PasswordAuthentication no'
    Set-Content -Path $config -Value $text -Encoding ascii
    New-Item -Path 'HKLM:\SOFTWARE\OpenSSH' -Force | Out-Null
    New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -PropertyType String -Force `
        -Value 'C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe' | Out-Null
    if (-not (Get-NetFirewallRule -Name 'fmcp-sshd' -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -Name 'fmcp-sshd' -DisplayName 'OpenSSH (FMCP)' -Direction Inbound `
            -Protocol TCP -LocalPort 22 -Action Allow | Out-Null
    }
    Restart-Service sshd
}

Step 'Python 3.14' {
    # The version the Mac's virtual environment uses; 3.14 also has Zstandard built in.
    $installer = 'C:\fmcp\downloads\python-3.14.8-amd64.exe'
    Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.14.8/python-3.14.8-amd64.exe' -OutFile $installer
    $run = Start-Process -FilePath $installer -Wait -PassThru `
        -ArgumentList '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0'
    if ($run.ExitCode -ne 0) { throw "installer exit code $($run.ExitCode)" }
}

Step 'Git' {
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/git-for-windows/git/releases/latest' `
        -Headers @{ 'User-Agent' = 'windows-setup' }
    $asset = $release.assets | Where-Object name -match '^Git-[\d.]+-64-bit\.exe$' | Select-Object -First 1
    if (-not $asset) { throw 'no 64-bit installer in the latest Git for Windows release' }
    $installer = "C:\fmcp\downloads\$($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installer
    $run = Start-Process -FilePath $installer -Wait -PassThru `
        -ArgumentList '/VERYSILENT', '/NORESTART', '/NOCANCEL', '/SP-'
    if ($run.ExitCode -ne 0) { throw "installer exit code $($run.ExitCode)" }
    # Keep files byte for byte as committed: the tests compare hashes of source files.
    & 'C:\Program Files\Git\cmd\git.exe' config --system core.autocrlf false
}

Step 'Zstandard library' {
    # The save-file readers load libzstd through ctypes; Windows has none. ctypes looks for
    # zstd.dll on PATH, so the official libzstd.dll is installed under that name.
    $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/facebook/zstd/releases/latest' `
        -Headers @{ 'User-Agent' = 'windows-setup' }
    $asset = $release.assets | Where-Object name -match '^zstd-v[\d.]+-win64\.zip$' | Select-Object -First 1
    if (-not $asset) { throw 'no win64 archive in the latest zstd release' }
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile C:\fmcp\downloads\zstd-win64.zip
    Expand-Archive C:\fmcp\downloads\zstd-win64.zip C:\fmcp\downloads\zstd -Force
    $dll = Get-ChildItem C:\fmcp\downloads\zstd -Recurse -Filter libzstd.dll | Select-Object -First 1
    if (-not $dll) { throw 'libzstd.dll is not in the archive' }
    New-Item -ItemType Directory -Force -Path C:\fmcp\bin | Out-Null
    Copy-Item $dll.FullName C:\fmcp\bin\zstd.dll -Force
    $path = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    if ($path -notlike '*C:\fmcp\bin*') {
        [Environment]::SetEnvironmentVariable('Path', "$path;C:\fmcp\bin", 'Machine')
    }
}

Step 'Long paths and work folders' {
    New-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -Name LongPathsEnabled `
        -PropertyType DWord -Value 1 -Force | Out-Null
    New-Item -ItemType Directory -Force -Path C:\fmcp\repo, C:\fmcp\evidence | Out-Null
}

Step 'Restart OpenSSH with the new PATH' {
    # sshd keeps the PATH it started with, which predates the Python and Git installs.
    Restart-Service sshd
}

if ($failed) { Log 'first boot finished with failures' } else { Log 'first boot complete' }
