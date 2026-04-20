# setup.ps1 - Cloudflare IP 优选工具一键部署脚本
# 功能：
#   1. 检测并安装依赖 (Python3, Git, curl, requests)
#   2. 自动创建 .gitignore 保护敏感信息
#   3. 自动创建/更新 Windows 计划任务（每15分钟运行 main.py）
#   4. 提供后续配置指引
# 使用方法：右键此文件 -> "使用 PowerShell 运行"（需管理员权限）

$ErrorActionPreference = "Stop"
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " Cloudflare IP 优选工具 - 智能部署" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ---------- 管理员权限检查 ----------
if (-NOT ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Host "❌ 错误：请以管理员身份运行此脚本！" -ForegroundColor Red
    Write-Host "方法：右键点击 setup.ps1 -> '使用 PowerShell 运行'。" -ForegroundColor Yellow
    pause
    exit 1
}

# ---------- 切换至脚本所在目录 ----------
Set-Location $PSScriptRoot
$ScriptDir = $PSScriptRoot
Write-Host "工作目录: $ScriptDir`n" -ForegroundColor Gray

# ==================== 计划任务配置（模仿 Cloudflare IP 优选.xml） ====================
$TaskName = "Cloudflare IP 优选"
$TaskDescription = "每15分钟运行一次 Cloudflare IP 优选工具，筛选最优节点并推送到 GitHub"
$TaskIntervalMinutes = 15
$TaskStartTime = (Get-Date).AddMinutes(2)          # 首次运行时间：2分钟后，避免立即触发
# 注意：以下路径会在检测到 Python 后自动更新
$PythonExePath = $null
$PythonScriptPath = Join-Path $ScriptDir "main.py"
$WorkingDirectory = $ScriptDir
$RunWithHighestPrivileges = $true
# =====================================================================================

# ---------- 检查 winget 可用性 ----------
$winget = Get-Command winget -ErrorAction SilentlyContinue
if (-not $winget) {
    Write-Host "❌ 未检测到 winget，无法自动安装软件。" -ForegroundColor Red
    Write-Host "请手动下载并安装以下组件：" -ForegroundColor White
    Write-Host "  - Python 3: https://www.python.org/downloads/"
    Write-Host "  - Git: https://git-scm.com/download/win"
    Write-Host "  - curl: https://curl.se/windows/"
    pause
    exit 1
}

# ---------- 1. 检测/安装 Python ----------
Write-Host "[1/4] 检查 Python..." -ForegroundColor Green
$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCmd) {
    $pythonCmd = Get-Command python3 -ErrorAction SilentlyContinue
}
if ($pythonCmd) {
    $PythonExePath = $pythonCmd.Source
    Write-Host "✅ Python 已安装: $PythonExePath" -ForegroundColor Gray
} else {
    Write-Host "未检测到 Python，正在通过 winget 安装 Python 3..." -ForegroundColor Yellow
    winget install Python.Python.3 --accept-package-agreements --accept-source-agreements
    # 刷新 PATH 环境变量
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
    # 再次尝试检测
    Start-Sleep -Seconds 3
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) {
        Write-Host "❌ 未能自动检测到 Python，请手动安装后重新运行本脚本。" -ForegroundColor Red
        pause
        exit 1
    }
    $PythonExePath = $pythonCmd.Source
    Write-Host "✅ Python 安装完成: $PythonExePath" -ForegroundColor Green
}

# ---------- 2. 检测/安装 Git ----------
Write-Host "[2/4] 检查 Git..." -ForegroundColor Green
$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    Write-Host "✅ Git 已安装: $($gitCmd.Source)" -ForegroundColor Gray
} else {
    Write-Host "正在通过 winget 安装 Git..." -ForegroundColor Yellow
    winget install Git.Git --accept-package-agreements --accept-source-agreements
    Write-Host "✅ Git 安装完成。" -ForegroundColor Green
}

# ---------- 3. 检测/安装 curl ----------
Write-Host "[3/4] 检查 curl..." -ForegroundColor Green
$curlCmd = Get-Command curl -ErrorAction SilentlyContinue
if ($curlCmd) {
    Write-Host "✅ curl 已安装: $($curlCmd.Source)" -ForegroundColor Gray
} else {
    Write-Host "正在通过 winget 安装 curl..." -ForegroundColor Yellow
    winget install cURL.cURL --accept-package-agreements --accept-source-agreements
    Write-Host "✅ curl 安装完成。" -ForegroundColor Green
}

# ---------- 4. 安装 Python 依赖 requests ----------
Write-Host "[4/4] 安装 Python 包 requests..." -ForegroundColor Green
& $PythonExePath -m pip install --upgrade pip --quiet
& $PythonExePath -m pip install requests --quiet
Write-Host "✅ requests 库安装完成。`n" -ForegroundColor Green

# ---------- 新增：自动生成 .gitignore (保护隐私) ----------
Write-Host "正在自动创建 .gitignore 保护隐私..." -ForegroundColor Green
$GitignorePath = Join-Path $ScriptDir ".gitignore"
$GitignoreContent = @"
# 敏感配置文件
config.json
git_sync.ps1

# Python 缓存
__pycache__/
*.pyc

# 运行结果
ip.txt
"@
try {
    $GitignoreContent | Out-File -FilePath $GitignorePath -Encoding utf8 -Force
    Write-Host "✅ .gitignore 已创建，已自动忽略敏感文件。" -ForegroundColor Gray
} catch {
    Write-Host "⚠️ 创建 .gitignore 失败，请稍后手动检查。" -ForegroundColor Yellow
}

# ---------- 5. 验证 main.py 是否存在 ----------
if (-not (Test-Path $PythonScriptPath)) {
    Write-Host "❌ 错误：未找到 main.py 文件，请确保脚本位于正确目录。" -ForegroundColor Red
    Write-Host "   预期位置: $PythonScriptPath" -ForegroundColor Yellow
    pause
    exit 1
}

# ---------- 6. 创建/更新 Windows 计划任务 ----------
Write-Host "正在配置 Windows 计划任务 '$TaskName' ..." -ForegroundColor Yellow

# 构建触发器：从 $TaskStartTime 开始，每 $TaskIntervalMinutes 分钟重复一次，无限期
$trigger = New-ScheduledTaskTrigger -Once `
    -At $TaskStartTime `
    -RepetitionInterval (New-TimeSpan -Minutes $TaskIntervalMinutes) `
    -RepetitionDuration ([System.TimeSpan]::MaxValue)

# 构建操作：通过 cmd /c start /high 启动 Python 脚本（模仿 XML 格式）
$arguments = "/c start `"`" /high `"$PythonExePath`" `"$PythonScriptPath`""
$action = New-ScheduledTaskAction -Execute "C:\Windows\System32\cmd.exe" `
    -Argument $arguments `
    -WorkingDirectory $WorkingDirectory

# 构建设置（与 XML 一致）
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstancesPolicy StopExisting `
    -Priority 7 `
    -ExecutionTimeLimit (New-TimeSpan -Days 3) `
    -AllowHardTerminate $true `
    -Compatibility Win8

# 构建主体：使用 SYSTEM 账户，无需密码，以最高权限运行
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel $(if ($RunWithHighestPrivileges) { "Highest" } else { "Limited" })

# 注册任务（强制覆盖已存在的同名任务）
try {
    Register-ScheduledTask -TaskName $TaskName `
        -Description $TaskDescription `
        -Trigger $trigger `
        -Action $action `
        -Settings $settings `
        -Principal $principal `
        -Force

    Write-Host "✅ 计划任务 '$TaskName' 创建成功！" -ForegroundColor Green
    Write-Host "   触发器: 每 $TaskIntervalMinutes 分钟一次（首次运行于 $TaskStartTime）" -ForegroundColor Gray
    Write-Host "   执行命令: $arguments" -ForegroundColor Gray
    Write-Host "   工作目录: $WorkingDirectory" -ForegroundColor Gray
} catch {
    Write-Host "❌ 创建计划任务失败: $_" -ForegroundColor Red
    pause
    exit 1
}

# ---------- 7. 后续配置指引 ----------
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host " 🎉 部署完成！" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "👉 接下来请完成以下手动配置步骤：" -ForegroundColor White
Write-Host "1. 【已完成】.gitignore 已自动生成，敏感文件将不会被 Git 追踪。" -ForegroundColor Gray
Write-Host "2. 编辑 config.json，填写 WxPusher 的 APP_TOKEN 和 UID（如需要通知功能）" -ForegroundColor White
Write-Host "3. 编辑 git_sync.ps1，填写你的 GitHub Token、用户名及仓库名" -ForegroundColor White
Write-Host "4. 可选：在'任务计划程序' (taskschd.msc) 中查看或调整任务" -ForegroundColor Gray
Write-Host "5. 手动运行一次测试：python main.py（或等待计划任务自动执行）" -ForegroundColor Green
Write-Host ""

# 询问是否立即运行一次测试
$response = Read-Host "是否立即运行一次 main.py 进行测试？(Y/N)"
if ($response -eq 'Y' -or $response -eq 'y') {
    Write-Host "正在运行 main.py ..." -ForegroundColor Cyan
    & $PythonExePath $PythonScriptPath
}

pause