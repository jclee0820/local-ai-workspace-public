' Local AI Workspace stopper: runs stop.ps1 without showing a console window (ASCII only on purpose)
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\stop.ps1""", 0, False
