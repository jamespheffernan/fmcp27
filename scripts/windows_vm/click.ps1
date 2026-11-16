# Click the left mouse button at a point of the desktop, in real pixels (run on the desktop).
#   powershell -File click.ps1 -X 906 -Y 565
param([Parameter(Mandatory)] [int] $X, [Parameter(Mandatory)] [int] $Y)
Add-Type -Namespace Native -Name Mouse -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
[DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[DllImport("user32.dll")] public static extern void mouse_event(uint flags, uint dx, uint dy, uint data, System.UIntPtr extra);
'@
[Native.Mouse]::SetProcessDPIAware() | Out-Null
[Native.Mouse]::SetCursorPos($X, $Y) | Out-Null
Start-Sleep -Milliseconds 150
[Native.Mouse]::mouse_event(2, 0, 0, 0, [System.UIntPtr]::Zero)   # left button down
Start-Sleep -Milliseconds 60
[Native.Mouse]::mouse_event(4, 0, 0, 0, [System.UIntPtr]::Zero)   # left button up
