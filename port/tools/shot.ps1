# Launches the port, waits, and screenshots its window.
#   shot.ps1 -Wait 20 -Out shot.png [-Keys "Enter,Enter"] [-KeyDelay 2]
param(
    [int]$Wait = 20,
    [string]$Out = "shot.png",
    [string]$Keys = "",
    [int]$KeyDelay = 2,
    [int]$Shots = 1,
    [int]$ShotGap = 3,
    [string]$Exe = "bin\Release\net10.0\XMenMA2.exe",
    [string]$Log = "run.log"
)

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr h, out RECT r);
    [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
}
"@

$exePath = Join-Path (Get-Location) $Exe
$dir = Split-Path $exePath
$proc = Start-Process -FilePath $exePath -WorkingDirectory $dir -PassThru `
        -RedirectStandardOutput (Join-Path $dir $Log) -RedirectStandardError (Join-Path $dir "$Log.err")

Start-Sleep -Seconds $Wait
if ($proc.HasExited) {
    Write-Output "process exited early with code $($proc.ExitCode)"
    exit 1
}

$proc.Refresh()
$h = $proc.MainWindowHandle
if ($h -eq [IntPtr]::Zero) {
    Write-Output "no window handle"
    $proc.Kill()
    exit 1
}

[void][Win32]::ShowWindow($h, 9)      # SW_RESTORE
[void][Win32]::SetForegroundWindow($h)
Start-Sleep -Milliseconds 800

if ($Keys -ne "") {
    foreach ($k in $Keys.Split(',')) {
        if ($k.Trim() -eq "") { continue }
        [System.Windows.Forms.SendKeys]::SendWait($k.Trim())
        Start-Sleep -Seconds $KeyDelay
    }
}

for ($i = 0; $i -lt $Shots; $i++) {
    if ($i -gt 0) { Start-Sleep -Seconds $ShotGap }
    [void][Win32]::SetForegroundWindow($h)
    $r = New-Object Win32+RECT
    [void][Win32]::GetClientRect($h, [ref]$r)
    $p = New-Object Win32+POINT
    [void][Win32]::ClientToScreen($h, [ref]$p)
    $w = $r.R - $r.L
    $hh = $r.B - $r.T
    if ($w -le 0 -or $hh -le 0) { Write-Output "bad client rect"; continue }
    $bmp = New-Object System.Drawing.Bitmap $w, $hh
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.CopyFromScreen($p.X, $p.Y, 0, 0, $bmp.Size)
    $name = if ($Shots -eq 1) { $Out } else {
        $od = [IO.Path]::GetDirectoryName($Out)
        $ob = [IO.Path]::GetFileNameWithoutExtension($Out)
        if ($od -eq "") { "$ob`_$i.png" } else { Join-Path $od "$ob`_$i.png" }
    }
    $full = Join-Path (Get-Location) $name
    $fd = Split-Path $full
    if (-not (Test-Path $fd)) { New-Item -ItemType Directory -Force $fd | Out-Null }
    $bmp.Save($full, [System.Drawing.Imaging.ImageFormat]::Png)
    $g.Dispose(); $bmp.Dispose()
    Write-Output "saved $name (${w}x${hh})"
}

$proc.Kill()
$proc.WaitForExit(5000)
Write-Output "done"
