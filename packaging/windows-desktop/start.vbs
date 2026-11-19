' Local AI Workspace launcher: runs start.ps1 without showing a console window (ASCII only on purpose)
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & here & "\start.ps1""", 0, False
