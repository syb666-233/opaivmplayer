# Start Luna without attaching to cmd.exe; auto-click tamper Warning (no SendKeys).
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot)
)

$Runtime = Join-Path $Root "runtime"
$Exe = Join-Path $Runtime "LunaTranslator.exe"

if (-not (Test-Path $Exe)) {
    exit 1
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class LunaLaunch {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowTextLength(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern IntPtr GetDlgItem(IntPtr hDlg, int nIDDlgItem);
    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    public const uint WM_COMMAND = 0x0111;
    public const uint BM_CLICK = 0x00F5;
    public const int IDYES = 6;
    public static IntPtr FindWarningDialog() {
        IntPtr h = FindWindow("#32770", "Warning");
        if (h != IntPtr.Zero) return h;
        h = FindWindow(null, "Warning");
        if (h != IntPtr.Zero) return h;
        IntPtr found = IntPtr.Zero;
        EnumWindows((hwnd, _) => {
            if (!IsWindowVisible(hwnd)) return true;
            int len = GetWindowTextLength(hwnd);
            if (len <= 0) return true;
            var sb = new StringBuilder(len + 1);
            GetWindowText(hwnd, sb, sb.Capacity);
            if (sb.ToString() == "Warning") { found = hwnd; return false; }
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static void ClickYes(IntPtr dlg) {
        if (dlg == IntPtr.Zero) return;
        IntPtr btn = GetDlgItem(dlg, IDYES);
        if (btn != IntPtr.Zero)
            SendMessage(btn, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
        SendMessage(dlg, WM_COMMAND, (IntPtr)IDYES, IntPtr.Zero);
    }
}
"@

$proc = Start-Process -FilePath $Exe -WorkingDirectory $Runtime -PassThru

for ($i = 0; $i -lt 50; $i++) {
    if ($proc.HasExited) { break }
    $delay = if ($i -lt 10) { 150 } else { 350 }
    Start-Sleep -Milliseconds $delay
    $hwnd = [LunaLaunch]::FindWarningDialog()
    if ($hwnd -ne [IntPtr]::Zero) {
        [LunaLaunch]::ClickYes($hwnd)
        break
    }
}

exit 0
