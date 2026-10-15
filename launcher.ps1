param([switch]$NoBrowser)

$ErrorActionPreference = 'Stop'
# 项目根目录 = 本脚本所在目录（克隆到任意路径均可运行）
$P = $PSScriptRoot
# v4.9.3：不写日志文件，运行输出全部走 stdout（控制台窗口直接可见，便于移植与打包）

function Write-Log([string]$m){
  Write-Host ('[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $m)
}
function Show-Alert([string]$m){
  try{
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($m, '联邦医院知识图谱AI 启动器') | Out-Null
  } catch { }
}
function Test-Service {
  try{
    Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/fl/status' -UseBasicParsing -TimeoutSec 3 | Out-Null
    return $true
  } catch {
    if($_.Exception.Response){ return $true }
    return $false
  }
}
function Find-Python {
  $cands = @(
    (Join-Path $P 'runtime\python.exe'),
    (Join-Path $P '.venv\Scripts\python.exe')
  )
  foreach($c in $cands){ if($c -and (Test-Path $c)){ return $c } }
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if($cmd){ return $cmd.Source }
  return $null
}

try{
  Write-Log '=== 启动检查 ==='
  if(Test-Service){
    Write-Log '服务已在运行'
  } else {
    Write-Log '服务未运行，尝试启动 MySQL80（已启动会自动跳过）'
    try{ Start-Process -FilePath 'net' -ArgumentList 'start','MYSQL80' -WindowStyle Hidden -ErrorAction SilentlyContinue } catch { Write-Log ('MySQL 启动命令异常：' + $_.Exception.Message) }

    $pyExe = Find-Python
    if(-not $pyExe){
      Write-Log '未找到可用的 Python 解释器'
      Show-Alert ('未找到可用的 Python 解释器（已尝试项目 runtime / .venv 与系统 python）。请查看本窗口上方的输出。')
      exit 1
    }
    Write-Log ('使用解释器：' + $pyExe)
    Start-Process -FilePath $pyExe -ArgumentList ('"' + (Join-Path $P 'app.py') + '"') -WorkingDirectory $P -WindowStyle Minimized

    $ok = $false
    for($i = 0; $i -lt 30; $i++){
      Start-Sleep -Milliseconds 800
      if(Test-Service){ $ok = $true; break }
    }
    if(-not $ok){
      Write-Log '等待约 24 秒后服务仍未就绪'
      Show-Alert ('后端启动失败或超时。请查看本窗口上方的输出。')
      exit 1
    }
    Write-Log '服务已就绪'
  }
  if(-not $NoBrowser){
    Start-Process 'http://localhost:5000'
    Write-Log '已在浏览器打开 http://localhost:5000'
  } else {
    Write-Log '（测试模式：未打开浏览器）'
  }
} catch {
  Write-Log ('发生异常：' + $_.Exception.Message)
  Show-Alert ('启动器发生异常：' + $_.Exception.Message)
}
