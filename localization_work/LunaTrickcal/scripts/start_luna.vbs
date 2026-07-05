' Launch Luna with hidden PowerShell (no cmd.exe window).
Option Explicit
Dim fso, sh, root, ps1, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
ps1 = fso.BuildPath(root, "scripts\launch_luna.ps1")
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1 & """ -Root """ & root & """"
sh.Run cmd, 0, False
