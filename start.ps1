# DreamyTale / 纸书智伴 —— 一键启动
# 用法: .\start.ps1 [-Port 8000] [-Offline] [-NoBrowser]
[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$Offline,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Fail([string]$message) {
    Write-Host "[启动失败] $message" -ForegroundColor Red
    exit 1
}

# 1. Python：优先项目内 .venv
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    $command = Get-Command python -ErrorAction SilentlyContinue
    if (-not $command) { Fail '找不到 Python。请安装 Python 3.11+ 并加入 PATH。' }
    $python = $command.Source
}
Write-Host "[1/4] Python: $python"

# 2. 运行依赖
& $python -c "import fastapi, uvicorn" 2>$null
if ($LASTEXITCODE -ne 0) {
    Fail "缺少运行依赖。先执行: `"$python`" -m pip install -r requirements.txt"
}

# 3. 离线开关
if ($Offline) {
    $env:DREAMYTALE_ANSWER_TTS = 'off'
    $env:HF_HUB_OFFLINE = '1'
    $env:TRANSFORMERS_OFFLINE = '1'
    Write-Host '[2/4] 离线模式：答案 TTS 关闭（前端用浏览器朗读），模型只读本机缓存'
} else {
    Write-Host '[2/4] 在线模式：答案语音走 edge-tts，失败时前端回退浏览器朗读'
}

# 4. 端口：已有本服务则直接打开，被别的程序占用则提示换端口
$url = "http://127.0.0.1:$Port"
$occupied = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($occupied) {
    $alive = $false
    try {
        $alive = (Invoke-WebRequest -UseBasicParsing -Uri "$url/health" -TimeoutSec 2).StatusCode -eq 200
    } catch { }
    if ($alive) {
        Write-Host "[3/4] 端口 $Port 上已有 DreamyTale 在运行，直接打开阅读器。"
        if (-not $NoBrowser) { Start-Process "$url/reader/" }
        exit 0
    }
    Fail "端口 $Port 被其他程序占用。换一个: .\start.ps1 -Port 8011"
}
Write-Host "[3/4] 端口 $Port 可用"

if (-not (Test-Path (Join-Path $root 'data\books'))) {
    Write-Host '[提示] 没有 data/books：书架会是空的，先按 README「快速开始」生成数据包。' -ForegroundColor Yellow
}

# 5. 服务就绪后自动打开阅读器
$openJob = $null
if (-not $NoBrowser) {
    $openJob = Start-Job -ScriptBlock {
        param($base)
        for ($i = 0; $i -lt 40; $i++) {
            try {
                if ((Invoke-WebRequest -UseBasicParsing -Uri "$base/health" -TimeoutSec 1).StatusCode -eq 200) {
                    Start-Process "$base/reader/"
                    return
                }
            } catch { }
            Start-Sleep -Milliseconds 500
        }
    } -ArgumentList $url
}

Write-Host "[4/4] 阅读器: $url/reader/   按 Ctrl+C 停止"
Write-Host ''

try {
    & $python -m uvicorn backend.app.c_demo:app --host 127.0.0.1 --port $Port
} finally {
    if ($openJob) {
        Stop-Job -Job $openJob -ErrorAction SilentlyContinue
        Remove-Job -Job $openJob -Force -ErrorAction SilentlyContinue
    }
}
