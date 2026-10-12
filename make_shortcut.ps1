# 在当前项目目录生成桌面快捷方式（克隆到任意路径均可使用）
$P = Split-Path -Parent $MyInvocation.MyCommand.Path
$Desktop = [Environment]::GetFolderPath('Desktop')
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut((Join-Path $Desktop '联邦医院知识图谱AI.lnk'))
$Shortcut.TargetPath = Join-Path $P '启动.bat'
$Shortcut.WorkingDirectory = $P
$Shortcut.Description = '联邦医院知识图谱AI - Flask+MySQL 一键启动'
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host ('Shortcut created -> ' + (Join-Path $Desktop '联邦医院知识图谱AI.lnk'))
