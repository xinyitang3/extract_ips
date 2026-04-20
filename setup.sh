#!/bin/bash
# setup.sh - Cloudflare IP 优选工具 Linux 一键部署脚本

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}========================================"
echo -e " Cloudflare IP 优选工具 - Linux 部署"
echo -e "========================================${NC}\n"

# 检查是否为 root（安装软件和 cron 可能需要）
if [[ $EUID -ne 0 ]]; then
   echo -e "${YELLOW}提示：建议使用 sudo 运行此脚本以确保顺利安装软件包和配置定时任务。${NC}"
fi

# 切换到脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
echo -e "工作目录: $SCRIPT_DIR\n"

# ---------- 1. 检测并安装依赖 ----------
echo -e "${GREEN}[1/4] 检查并安装系统依赖...${NC}"

# 检测包管理器并安装 python3, python3-pip, git, curl
if command -v apt-get &> /dev/null; then
    PKG_MANAGER="apt-get"
    sudo apt-get update
    sudo apt-get install -y python3 python3-pip git curl
elif command -v yum &> /dev/null; then
    PKG_MANAGER="yum"
    sudo yum install -y python3 python3-pip git curl
elif command -v dnf &> /dev/null; then
    PKG_MANAGER="dnf"
    sudo dnf install -y python3 python3-pip git curl
elif command -v pacman &> /dev/null; then
    PKG_MANAGER="pacman"
    sudo pacman -S --noconfirm python python-pip git curl
else
    echo -e "${RED}❌ 未检测到支持的包管理器，请手动安装 python3, pip, git, curl${NC}"
    exit 1
fi

# ---------- 2. 安装 Python 依赖 ----------
echo -e "${GREEN}[2/4] 安装 Python 包 requests...${NC}"
python3 -m pip install --upgrade pip --quiet
python3 -m pip install requests --quiet
echo -e "${GREEN}✅ requests 安装完成${NC}\n"

# ---------- 3. 创建 .gitignore 保护隐私 ----------
echo -e "${GREEN}[3/4] 创建 .gitignore 保护敏感文件...${NC}"
cat > .gitignore << 'EOF'
# 敏感配置文件
config.json
git_sync.sh
git_sync.ps1

# Python 缓存
__pycache__/
*.pyc

# 运行结果
ip.txt
EOF
echo -e "${GREEN}✅ .gitignore 已创建${NC}"

# ---------- 4. 设置 cron 定时任务 ----------
echo -e "${GREEN}[4/4] 配置定时任务（每15分钟运行一次）...${NC}"

CRON_CMD="*/15 * * * * cd $SCRIPT_DIR && /usr/bin/python3 $SCRIPT_DIR/main.py >> $SCRIPT_DIR/cron.log 2>&1"
CRON_COMMENT="# Cloudflare IP 优选工具定时任务"

# 检查是否已存在该任务，避免重复添加
(sudo crontab -l 2>/dev/null | grep -v "$SCRIPT_DIR/main.py" || true; echo "$CRON_COMMENT"; echo "$CRON_CMD") | sudo crontab -

echo -e "${GREEN}✅ 定时任务已添加（每15分钟）${NC}"
echo -e "   查看日志: tail -f $SCRIPT_DIR/cron.log"

# ---------- 5. 后续指引 ----------
echo ""
echo -e "${CYAN}========================================"
echo -e " 🎉 部署完成！"
echo -e "========================================${NC}\n"
echo -e "${YELLOW}👉 接下来请手动完成以下配置：${NC}"
echo -e "1. 编辑 config.json，填写 WxPusher 的 APP_TOKEN 和 UID（如需通知）"
echo -e "2. 编辑 git_sync.sh，填写你的 GitHub Token、用户名及仓库名"
echo -e "3. 给 git_sync.sh 执行权限: ${CYAN}chmod +x git_sync.sh${NC}"
echo -e "4. 手动运行一次测试: ${CYAN}python3 main.py${NC}"
echo ""

# 询问是否立即运行
read -p "是否立即运行一次 main.py 进行测试？(y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${CYAN}正在运行 main.py ...${NC}"
    python3 main.py
fi