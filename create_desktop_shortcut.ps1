$ErrorActionPreference = 'Stop'
$publishRoot = $PSScriptRoot
$desktopDirectory = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopDirectory '三端批量发布.lnk'
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$shortcut.Arguments = '"' + (Join-Path $publishRoot 'multi_publish.vbs') + '"'
$shortcut.WorkingDirectory = $publishRoot
$shortcut.IconLocation = (Join-Path $publishRoot 'assets\creator-publish.ico') + ',0'
$shortcut.Description = 'B站、抖音、小红书三端发布，保留作品和各平台状态'
$shortcut.Save()
Write-Output $shortcutPath
