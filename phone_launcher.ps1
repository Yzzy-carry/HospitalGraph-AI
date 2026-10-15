param([switch]$Stop)

$ErrorActionPreference = 'Stop'
# 项目根目录 = 本脚本所在目录
$P = $PSScriptRoot
# v4.9.3：不写日志文件，运行输出全部走 stdout（便于移植与打包）

function Write-Log([string]$m){
  Write-Host ('[' + (Get-Date -Format 'HH:mm:ss') + '] ' + $m)
}
function Show-Alert([string]$m){
  try{
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($m, '联邦医院知识图谱AI · 手机访问') | Out-Null
  } catch {}
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
function Get-HgProcs {
  $all = @(Get-CimInstance Win32_Process -Filter "Name LIKE 'python%'" -ErrorAction SilentlyContinue)
  $ids = @()
  $ids += @(Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess)
  $ids += @($all | Where-Object { $_.CommandLine -and ($_.CommandLine -like '*HospitalGraph-AI*' -or ($_.CommandLine -like '*app.py*' -and ([string]$_.ExecutablePath) -match 'pycharm|anaconda|WindowsApps|HospitalGraph-AI')) } | Select-Object -ExpandProperty ProcessId)
  foreach($p in $all){ if($ids -contains [int]$p.ParentProcessId){ $ids += [int]$p.ProcessId } }
  $ids = @($ids | Sort-Object -Unique)
  @($all | Where-Object { $ids -contains [int]$_.ProcessId })
}
function Test-LocalService {
  try{
    Invoke-WebRequest -Uri 'http://127.0.0.1:5000/api/fl/status' -UseBasicParsing -TimeoutSec 3 | Out-Null
    return $true
  } catch {
    if($_.Exception.Response){ return $true }
    return $false
  }
}
function Get-LanIp {
  try{
    $r = Find-NetRoute -RemoteIPAddress '8.8.8.8' -ErrorAction SilentlyContinue |
      Where-Object { $_.IPAddress -and $_.IPAddress -notlike '127.*' } | Select-Object -First 1
    if($r){ return $r.IPAddress }
  } catch {}
  $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } | Select-Object -First 1
  if($ip){ return $ip.IPAddress }
  return $null
}
function Test-FirewallRule {
  netsh advfirewall firewall show rule name=HospitalGraph-AI-TCP5000 | Out-Null
  return ($LASTEXITCODE -eq 0)
}
function Stop-HgService {
  $procs = Get-HgProcs
  if(-not $procs){ Write-Log '未发现运行中的服务进程'; return $false }
  foreach($pr in $procs){
    Write-Log ('停止进程 PID ' + $pr.ProcessId + ' …')
    Stop-Process -Id $pr.ProcessId -Force -ErrorAction SilentlyContinue
  }
  for($k = 0; $k -lt 10; $k++){
    Start-Sleep -Milliseconds 300
    if(-not (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)){ break }
  }
  return $true
}

if($Stop){
  Write-Log '=== 停止服务 ==='
  Stop-HgService | Out-Null
  Write-Log '完成。'
  Write-Host ''
  Write-Host '按回车键关闭本窗口'
  Read-Host | Out-Null
  exit 0
}

try{
  Write-Log '=== 手机访问模式 ==='
  $listen = Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue
  $lanReady = $false
  if($listen){ $lanReady = [bool]($listen | Where-Object { $_.LocalAddress -eq '0.0.0.0' -or $_.LocalAddress -eq '::' }) }
  if($listen -and -not $lanReady){
    if(-not (Get-HgProcs)){
      Write-Log '端口 5000 被其他程序占用'
      Show-Alert '端口 5000 正被其他程序占用，请先关闭它再试。'
      exit 1
    }
    Write-Log '服务当前仅本机可访问，切换为手机访问模式…'
    Stop-HgService | Out-Null
    $listen = $null
  }
  if(-not $listen){
    try{ Start-Process -FilePath 'net' -ArgumentList 'start','MYSQL80' -WindowStyle Hidden -ErrorAction SilentlyContinue } catch {}
    $pyExe = Find-Python
    if(-not $pyExe){ Write-Log '未找到 Python'; Show-Alert '未找到 Python 解释器（详情见本窗口输出）'; exit 1 }
    $env:HG_HOST = '0.0.0.0'
    $env:HG_DEBUG = '0'
    Start-Process -FilePath $pyExe -ArgumentList ('"' + (Join-Path $P 'app.py') + '"') -WorkingDirectory $P -WindowStyle Minimized
    $ok = $false
    for($i = 0; $i -lt 30; $i++){
      Start-Sleep -Milliseconds 800
      if(Test-LocalService){ $ok = $true; break }
    }
    if(-not $ok){ Write-Log '服务启动超时'; Show-Alert '启动超时（详情见本窗口输出）'; exit 1 }
    Write-Log '服务已就绪（局域网模式，调试已关闭）'
  } else {
    Write-Log '服务已在手机访问模式运行'
  }

  $ip = Get-LanIp
  if(-not $ip){
    Write-Log '未检测到局域网 IP —— 请检查电脑网络后重新运行'
    Show-Alert '未检测到局域网 IP：请确认电脑已连接网络（Wi-Fi 或网线）后重新运行启动器。'
    $ip = '127.0.0.1'
  }
  $url = 'http://' + $ip + ':5000'
  Write-Host ''
  Write-Host '=============================================='
  Write-Host ('  手机访问地址： ' + $url)
  Write-Host '  手机与电脑连同一网络，浏览器打开（或扫码）'
  Write-Host '=============================================='
  Write-Log ('手机访问地址：' + $url)

  if(Test-FirewallRule){ Write-Log '防火墙规则已就绪（HospitalGraph-AI-TCP5000）' }
  else{
    Write-Log '未找到防火墙规则，尝试添加（会弹出管理员授权）…'
    try{
      Start-Process -FilePath 'netsh' -Verb RunAs -WindowStyle Hidden -ArgumentList 'advfirewall firewall add rule name=HospitalGraph-AI-TCP5000 dir=in action=allow protocol=TCP localport=5000 remoteip=LocalSubnet profile=any'
      Start-Sleep -Seconds 3
    } catch { Write-Log ('防火墙规则添加异常：' + $_.Exception.Message) }
    if(Test-FirewallRule){ Write-Log '防火墙规则已添加' }
    else{ Write-Log '防火墙规则仍未就绪（可在弹窗点"是"，或手动放行 5000 端口）'; Show-Alert '提示：如果手机连不上，请允许 Windows 防火墙对 5000 端口的访问。' }
  }

  try{
    $qrp = Join-Path $env:TEMP 'hg_phone_qr.png'  # v4.9.3：存系统临时目录，不往项目里写文件
    $qrCode = 'import qrcode,sys; qrcode.make(sys.argv[1]).save(sys.argv[2])'
    $qrCands = @()
    if($pyExe){ $qrCands += $pyExe }
    $qrCands += (Find-Python)
    $qrPy = $null
    foreach($c in ($qrCands | Where-Object { $_ } | Select-Object -Unique)){
      if(Test-Path $c){
        & $c -c 'import qrcode' 2>$null | Out-Null
        if($LASTEXITCODE -eq 0){ $qrPy = $c; break }
      }
    }
    if($qrPy){
      & $qrPy -c $qrCode $url $qrp 2>$null | Out-Null
      if(Test-Path $qrp){ Start-Process $qrp; Write-Log '二维码已生成并打开' }
      else{ Write-Log '二维码生成失败（可忽略，不影响使用）' }
    } else {
      Write-Log '未找到带 qrcode 库的 Python，跳过二维码（不影响使用）'
    }
  } catch { Write-Log ('二维码生成失败：' + $_.Exception.Message) }
} catch {
  Write-Log ('发生异常：' + $_.Exception.Message)
  Show-Alert ('手机访问启动器异常：' + $_.Exception.Message)
}
Write-Host ''
Write-Host '按回车键关闭本窗口（不会关闭服务）'
Read-Host | Out-Null
