$ErrorActionPreference = 'SilentlyContinue'
function Test-Port5000 {
  $c = New-Object Net.Sockets.TcpClient
  $ok = $c.ConnectAsync('127.0.0.1', 5000).Wait(600) -and $c.Connected
  $c.Close()
  return $ok
}
if (-not (Test-Port5000)) {
  Start-Process -FilePath 'net' -ArgumentList 'start','MYSQL80' -WindowStyle Hidden
  Start-Sleep -Seconds 2
  Start-Process -FilePath 'C:\Users\user\Desktop\pycharm项目文件夹\.venv\Scripts\python.exe' -ArgumentList '"C:\Users\user\Desktop\HospitalGraph-AI\app.py"' -WorkingDirectory 'C:\Users\user\Desktop\HospitalGraph-AI' -WindowStyle Minimized
  $waited = 0
  while (-not (Test-Port5000) -and $waited -lt 15) { Start-Sleep -Milliseconds 800; $waited++ }
}
Start-Process 'http://localhost:5000'
