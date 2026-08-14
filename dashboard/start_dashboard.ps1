[CmdletBinding()]
param(
    [string]$DashboardHost = '127.0.0.1',
    [ValidateRange(1, 65535)]
    [int]$Port = 8765,
    [ValidateRange(5, 120)]
    [int]$StartupTimeoutSeconds = 45,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$pythonPath = $null
$pythonCandidates = @(
    $env:QUANT_DASHBOARD_PYTHON,
    (Join-Path $projectRoot '.venv\Scripts\python.exe')
)
foreach ($candidate in $pythonCandidates) {
    if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
        $pythonPath = [System.IO.Path]::GetFullPath($candidate)
        break
    }
}
if (-not $pythonPath) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and (Test-Path -LiteralPath $pythonCommand.Source -PathType Leaf)) {
        $pythonPath = $pythonCommand.Source
    }
}
$serverPath = Join-Path $projectRoot 'dashboard\server.py'
$runtimeDirectory = Join-Path $projectRoot 'data\processed\dashboard'
$pidFile = Join-Path $runtimeDirectory 'dashboard.pid.json'
$stdoutLog = Join-Path $runtimeDirectory 'dashboard.stdout.log'
$stderrLog = Join-Path $runtimeDirectory 'dashboard.stderr.log'
$dashboardUrl = "http://${DashboardHost}:$Port"
$healthUrl = "$dashboardUrl/api/ping"

function Write-Status([string]$Message) {
    Write-Host "[QuantPilot] $Message"
}

function Test-DashboardHealth {
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -Method Get -TimeoutSec 2
        return $response.ok -eq $true -and $response.service -eq 'quantpilot-dashboard'
    }
    catch {
        return $false
    }
}

function Get-ListeningProcess {
    $connection = Get-NetTCPConnection -LocalAddress $DashboardHost -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
            Select-Object -First 1
    }
    if (-not $connection) {
        return $null
    }
    return Get-CimInstance Win32_Process -Filter "ProcessId = $($connection.OwningProcess)" -ErrorAction SilentlyContinue
}

function Get-ProcessTree([int]$RootProcessId) {
    $found = [System.Collections.Generic.List[int]]::new()
    $pending = [System.Collections.Generic.Queue[int]]::new()
    $pending.Enqueue($RootProcessId)
    while ($pending.Count -gt 0) {
        $current = $pending.Dequeue()
        if ($found.Contains($current)) {
            continue
        }
        $found.Add($current)
        Get-CimInstance Win32_Process -Filter "ParentProcessId = $current" -ErrorAction SilentlyContinue |
            ForEach-Object { $pending.Enqueue([int]$_.ProcessId) }
    }
    return $found
}

function Stop-RecordedDashboard {
    if (-not (Test-Path -LiteralPath $pidFile)) {
        return
    }
    try {
        $record = Get-Content -Raw -Encoding UTF8 -LiteralPath $pidFile | ConvertFrom-Json
        $rootProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
        if (-not $rootProcess) {
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
            return
        }
        $expectedServer = [string]$record.server
        if ($rootProcess.Name -notmatch '^python(w)?\.exe$' -or
            $rootProcess.CommandLine -notlike '*dashboard*server.py*' -or
            $expectedServer -ne $serverPath) {
            throw "PID 文件指向的不是本项目面板进程，已拒绝清理：PID $($rootProcess.ProcessId)"
        }
        Write-Status "正在清理上次未正常退出的面板进程（PID $($rootProcess.ProcessId)）..."
        $processIds = @(Get-ProcessTree -RootProcessId ([int]$rootProcess.ProcessId))
        [array]::Reverse($processIds)
        foreach ($processId in $processIds) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        }
        Start-Sleep -Milliseconds 700
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
    catch {
        throw "无法清理旧面板进程：$($_.Exception.Message)"
    }
}

function Open-Dashboard {
    if (-not $NoBrowser) {
        Start-Process $dashboardUrl
    }
}

try {
    Write-Status "正在检查启动环境..."
    if (-not $pythonPath) {
        throw "找不到 Python。请先执行 python -m venv .venv，再执行 .venv\Scripts\pip install -r requirements.txt。"
    }
    if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
        throw "找不到面板服务：$serverPath"
    }
    New-Item -ItemType Directory -Path $runtimeDirectory -Force | Out-Null

    & $pythonPath -c "import numpy, pandas" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "当前 Python 缺少依赖。请执行 `"$pythonPath`" -m pip install -r `"$projectRoot\requirements.txt`"。"
    }

    if (Test-DashboardHealth) {
        Write-Status "面板已经在运行，直接打开浏览器。"
        Open-Dashboard
        exit 0
    }

    Stop-RecordedDashboard

    $listener = Get-ListeningProcess
    if ($listener) {
        throw "端口 $Port 已被其他程序占用：$($listener.Name)（PID $($listener.ProcessId)）。请关闭该程序，或查看 $stderrLog。"
    }

    Remove-Item -LiteralPath $stdoutLog, $stderrLog -Force -ErrorAction SilentlyContinue
    Write-Status "正在启动服务，首次启动可能需要数秒..."
    $arguments = @('-u', $serverPath, '--host', $DashboardHost, '--port', [string]$Port)
    $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $projectRoot `
        -WindowStyle Hidden -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog -PassThru

    @{
        pid = $process.Id
        server = $serverPath
        port = $Port
        started_at = (Get-Date).ToString('o')
    } | ConvertTo-Json | Set-Content -LiteralPath $pidFile -Encoding UTF8

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    do {
        Start-Sleep -Milliseconds 500
        if (Test-DashboardHealth) {
            Write-Status "启动成功：$dashboardUrl"
            Open-Dashboard
            exit 0
        }
    } while ((Get-Date) -lt $deadline)

    $details = ''
    if (Test-Path -LiteralPath $stderrLog) {
        $details = (Get-Content -Tail 20 -Encoding UTF8 -LiteralPath $stderrLog) -join [Environment]::NewLine
    }
    if (-not $details -and (Test-Path -LiteralPath $stdoutLog)) {
        $details = (Get-Content -Tail 20 -Encoding UTF8 -LiteralPath $stdoutLog) -join [Environment]::NewLine
    }
    if (-not $details) {
        $details = '服务没有返回健康状态，也没有生成错误日志。'
    }
    throw "服务在 $StartupTimeoutSeconds 秒内未能启动。`n$details"
}
catch {
    Write-Host ''
    Write-Host "[启动失败] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "错误日志：$stderrLog" -ForegroundColor Yellow
    exit 1
}
