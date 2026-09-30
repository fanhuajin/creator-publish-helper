$ErrorActionPreference = 'Stop'
$pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw '请先按 README 安装 Python、创建 .venv 并安装依赖。'
    }
    & $pythonPath -u -X utf8 (Join-Path $PSScriptRoot 'fill_helper.py')
    if ($LASTEXITCODE -ne 0) {
        throw "助手退出，退出码：$LASTEXITCODE"
    }
} catch {
    Write-Host $_.Exception.Message
}
Read-Host '按回车关闭'
