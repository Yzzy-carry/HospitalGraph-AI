
$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut("C:\Users\user\Desktop\联邦医院知识图谱AI.lnk")
$Shortcut.TargetPath = "C:\Users\user\Desktop\HospitalGraph-AI\启动.bat"
$Shortcut.WorkingDirectory = "C:\Users\user\Desktop\HospitalGraph-AI"
$Shortcut.Description = "联邦医院知识图谱AI - Flask+MySQL 一键启动"
$Shortcut.WindowStyle = 7
$Shortcut.Save()
Write-Host "Shortcut created"
