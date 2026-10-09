Option Explicit
Dim shell, files, base, runner, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
base = files.GetParentFolderName(WScript.ScriptFullName)
runner = base & "\.venv\Scripts\uv.exe"
If Not files.FileExists(runner) Then
    runner = shell.ExpandEnvironmentStrings("%USERPROFILE%") & "\.local\bin\uv.exe"
End If
If Not files.FileExists(runner) Then runner = "uv"
shell.CurrentDirectory = base
command = """" & runner & """ run --no-project --python 3.13 --with windows-mcp==0.8.5 python -B -u -X utf8 """ & base & "\multi_publish.py"""
shell.Run command, 0, False
