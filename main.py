#!/usr/bin/env python3
"""
Cloudflare IP 优选工具 (TCP筛选 + IP可用性二次筛选 + curl带宽测速 + WxPusher通知)
依赖：requests, curl (系统自带)
配置文件：同目录下的 config.json（请根据需要修改参数）
结果保存到 ip.txt，并自动推送到 GitHub，同时批量更新到 Cloudflare DNS
支持 Windows / Linux
优化：国家过滤前置，减少无效 TCP 测试；重试参数可配置
"""

import requests
import socket
import time
import sys
import re
import os
import subprocess
import shutil
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# 全局 socket 默认超时兜底，防止任何未显式设置超时的操作永久阻塞
socket.setdefaulttimeout(10)

# ==================== 加载配置文件 ====================
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

def load_config():
    """加载 config.json 配置文件，缺失必填字段时抛出异常"""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ 错误：未找到配置文件 {CONFIG_FILE}")
        print("请在同目录下创建 config.json 文件，内容参考示例。")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"❌ 错误：配置文件格式不正确 - {e}")
        sys.exit(1)

    # 定义必填字段及其默认值（若配置文件中缺失则使用默认值）
    defaults = {
        "USE_GLOBAL_MODE": True,
        "TCP_PROBES": 7,
        "MIN_SUCCESS_RATE": 1.0,
        "TEST_AVAILABILITY": True,
        "FILTER_IPV6_AVAILABILITY": True,
        "BANDWIDTH_CANDIDATES": 32,
        "GLOBAL_TOP_N": 16,
        "PER_COUNTRY_TOP_N": 1,
        "MAX_WORKERS": 150,
        "AVAILABILITY_WORKERS": 20,
        "BANDWIDTH_WORKERS": 6,
        "TIMEOUT": 2.5,
        "AVAILABILITY_TIMEOUT": 8,
        "BANDWIDTH_TIMEOUT": 5,
        "BANDWIDTH_SIZE_MB": 1,
        "JSON_URL": "https://zip.cm.edu.kg/all.txt",
        "AVAILABILITY_CHECK_API": "https://check-proxyip-api.cmliussss.net/check",
        "BANDWIDTH_URL_TEMPLATE": "https://speed.cloudflare.com/__down?bytes={bytes}",
        "OUTPUT_FILE": "ip.txt",
        "FILTER_COUNTRIES_ENABLED": False,
        "ALLOWED_COUNTRIES": [],
        "ENABLE_WXPUSHER": True,
        "WXPUSHER_APP_TOKEN": "",
        "WXPUSHER_UIDS": [],
        "WXPUSHER_API_URL": "http://wxpusher.zjiecode.com/api/send/message",
        "CF_ENABLED": False,
        "CF_API_TOKEN": "",
        "CF_ZONE_ID": "",
        "CF_DNS_RECORD_NAME": "",
        "CF_TTL": 60,
        "CF_PROXIED": False,
        "DNS_UPDATE_MAX_RETRIES": 5,
        "DNS_UPDATE_RETRY_DELAY": 10,
        "GITHUB_SYNC_MAX_RETRIES": 5,
        "GITHUB_SYNC_RETRY_DELAY": 10
    }

    # 用默认值补全缺失字段
    for key, value in defaults.items():
        if key not in config:
            config[key] = value
            print(f"⚠️ 配置项 {key} 未设置，使用默认值：{value}")

    return config

# 加载配置
cfg = load_config()

# 从配置中读取各项参数
USE_GLOBAL_MODE = cfg["USE_GLOBAL_MODE"]
TCP_PROBES = cfg["TCP_PROBES"]
MIN_SUCCESS_RATE = cfg["MIN_SUCCESS_RATE"]
TEST_AVAILABILITY = cfg["TEST_AVAILABILITY"]
FILTER_IPV6_AVAILABILITY = cfg["FILTER_IPV6_AVAILABILITY"]
BANDWIDTH_CANDIDATES = cfg["BANDWIDTH_CANDIDATES"]
GLOBAL_TOP_N = cfg["GLOBAL_TOP_N"]
PER_COUNTRY_TOP_N = cfg["PER_COUNTRY_TOP_N"]
MAX_WORKERS = cfg["MAX_WORKERS"]
AVAILABILITY_WORKERS = cfg["AVAILABILITY_WORKERS"]
BANDWIDTH_WORKERS = cfg["BANDWIDTH_WORKERS"]
TIMEOUT = cfg["TIMEOUT"]
AVAILABILITY_TIMEOUT = cfg["AVAILABILITY_TIMEOUT"]
BANDWIDTH_TIMEOUT = cfg["BANDWIDTH_TIMEOUT"]
BANDWIDTH_SIZE_MB = cfg["BANDWIDTH_SIZE_MB"]
JSON_URL = cfg["JSON_URL"]
AVAILABILITY_CHECK_API = cfg["AVAILABILITY_CHECK_API"]
BANDWIDTH_URL_TEMPLATE = cfg["BANDWIDTH_URL_TEMPLATE"]
OUTPUT_FILE = cfg["OUTPUT_FILE"]
FILTER_COUNTRIES_ENABLED = cfg["FILTER_COUNTRIES_ENABLED"]
ALLOWED_COUNTRIES = cfg["ALLOWED_COUNTRIES"]
ENABLE_WXPUSHER = cfg["ENABLE_WXPUSHER"]
WXPUSHER_APP_TOKEN = cfg["WXPUSHER_APP_TOKEN"]
WXPUSHER_UIDS = cfg["WXPUSHER_UIDS"]
WXPUSHER_API_URL = cfg["WXPUSHER_API_URL"]

# 动态生成带宽测速完整 URL
BANDWIDTH_URL = BANDWIDTH_URL_TEMPLATE.format(bytes=BANDWIDTH_SIZE_MB * 1024 * 1024)

# ====================================================

def send_wxpusher_notification(content, summary):
    """发送 WxPusher 微信通知"""
    if not ENABLE_WXPUSHER:
        return
    try:
        payload = {
            "appToken": WXPUSHER_APP_TOKEN,
            "content": content,
            "summary": summary,
            "uids": WXPUSHER_UIDS
        }
        headers = {"Content-Type": "application/json; charset=utf-8"}
        resp = requests.post(WXPUSHER_API_URL, data=json.dumps(payload), headers=headers, timeout=10)
        if resp.status_code == 200:
            print("✅ 微信通知已发送")
        else:
            print(f"⚠️ 微信通知发送失败: {resp.status_code}")
    except Exception as e:
        print(f"⚠️ 微信通知异常: {e}")

def fetch_nodes():
    """从远程 TXT 获取所有节点，每行格式：IP:端口#国家，支持自动重试"""
    max_retries = 5
    retry_delay = 5

    for attempt in range(1, max_retries + 1):
        try:
            print(f"正在请求 {JSON_URL} (尝试 {attempt}/{max_retries}) ...")
            resp = requests.get(JSON_URL, timeout=10)
            resp.raise_for_status()
            # 按行读取，过滤空行和注释
            lines = [line.strip() for line in resp.text.splitlines() if line.strip() and not line.startswith('#')]
            nodes = []
            for line in lines:
                # 验证格式：IP:端口#国家
                if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+#[A-Z]{2}$", line):
                    nodes.append(line)
                else:
                    print(f"警告：跳过格式不正确的行：{line}")
            print(f"成功解析 {len(nodes)} 个节点。")
            return nodes

        except Exception as e:
            print(f"请求或解析失败: {e}")
            if attempt < max_retries:
                print(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                print(f"已尝试 {max_retries} 次，获取节点失败，退出。")
                send_wxpusher_notification(
                    content=f"获取 Cloudflare IP 列表失败，已重试 {max_retries} 次。错误：{e}",
                    summary="获取 Cloudflare IP 列表失败"
                )
                sys.exit(1)

def test_tcp_latency(ip, port, timeout=TIMEOUT, probes=TCP_PROBES):
    """
    多次测试 TCP 连接，返回 (最小延迟秒数, 成功次数)。
    若全部失败则最小延迟为 inf。
    """
    min_latency = float("inf")
    success = 0
    for _ in range(probes):
        try:
            start = time.time()
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect((ip, int(port)))
            latency = time.time() - start
            if latency < min_latency:
                min_latency = latency
            success += 1
        except Exception:
            continue
    return min_latency, success

def test_node(node_str):
    """
    处理单个节点字符串，进行 TCP 测试并过滤成功率。
    测试成功返回 (原始节点字符串, 最小延迟秒数, 国家代码, 成功次数)，
    测试失败或成功率不足返回 None。
    """
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)#(.+)$", node_str)
    if not m:
        return None
    ip, port, country = m.groups()
    min_lat, success = test_tcp_latency(ip, port)

    if success == 0 or (success / TCP_PROBES) < MIN_SUCCESS_RATE:
        return None

    return (node_str, min_lat, country, success)

def check_availability(node_str):
    """
    检测单个节点是否可用（通过 check-proxyip-api）
    返回 (node_str, is_ok, returned_ip)
    """
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)#", node_str)
    if not m:
        return (node_str, False, "")
    ip, port = m.group(1), m.group(2)
    proxyip = f"{ip}:{port}"

    try:
        resp = requests.get(
            AVAILABILITY_CHECK_API,
            params={"proxyip": proxyip},
            timeout=AVAILABILITY_TIMEOUT
        )
        if resp.status_code == 200:
            data = resp.json()
            if data.get("success") is True:
                returned_ip = data.get("ip", "")
                return (node_str, True, returned_ip)
    except Exception:
        pass
    return (node_str, False, "")

def availability_filter_candidates(candidates):
    """
    对候选节点进行可用性二次筛选
    返回 (passed_nodes, ip_info)
        - passed_nodes: 通过检测的节点列表
        - ip_info: 字典，key=完整节点字符串，value=落地IP
    - 若通过率 = 0%（全部失败），发送微信告警，返回原候选列表（跳过过滤）
    """
    if not TEST_AVAILABILITY or not candidates:
        return candidates, {}

    print(f"\n对 {len(candidates)} 个候选节点进行可用性二次筛选...")
    passed = []
    ip_info = {}
    completed = 0
    total = len(candidates)
    last_print = time.time()

    with ThreadPoolExecutor(max_workers=AVAILABILITY_WORKERS) as executor:
        futures = {executor.submit(check_availability, node): node for node in candidates}
        for future in as_completed(futures):
            completed += 1
            node_str, ok, returned_ip = future.result()
            if ok:
                passed.append(node_str)
                ip_info[node_str] = returned_ip
            now = time.time()
            if now - last_print >= 0.5 or completed == total:
                print(f"\r[可用性检测] 进度：{completed}/{total} ({(completed/total)*100:.1f}%) 通过数量：{len(passed)}", end="", flush=True)
                last_print = now
    print()

    if len(passed) == 0:
        print(f"⚠️ 可用性检测通过率为 0%，将跳过过滤，使用原候选列表继续。")
        send_wxpusher_notification(
            content=f"IP 可用性检测 API 疑似失效，{total} 个候选节点全部未通过，已自动跳过过滤。",
            summary="可用性 API 异常"
        )
        return candidates, {}   # 返回原列表，落地信息为空
    else:
        print(f"可用性检测完成，通过数量：{len(passed)} / {total}")
        return passed, ip_info

def measure_bandwidth_curl(node_str):
    """
    使用系统 curl 命令测速，返回 (node_str, speed_mbps)
    """
    m = re.match(r"^(\d+\.\d+\.\d+\.\d+):(\d+)#", node_str)
    if not m:
        return (node_str, 0)
    ip, port = m.group(1), m.group(2)

    null_device = "NUL" if sys.platform == "win32" else "/dev/null"
    curl_cmd = [
        "curl", "-s", "-o", null_device,
        "-w", "%{size_download} %{time_total}",
        "--resolve", f"speed.cloudflare.com:{port}:{ip}",
        "--max-time", str(BANDWIDTH_TIMEOUT),
        "--insecure",
        BANDWIDTH_URL
    ]

    try:
        # 超时保护增强：BANDWIDTH_TIMEOUT + 5 秒，防止极端网络下 curl 进程僵死
        result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=BANDWIDTH_TIMEOUT + 5)
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split()
            if len(parts) >= 2:
                size_bytes = float(parts[0])
                time_total = float(parts[1])
                if time_total > 0 and size_bytes > 0:
                    speed_mbps = (size_bytes * 8) / (time_total * 1000 * 1000)
                    return (node_str, speed_mbps)
    except Exception:
        pass
    return (node_str, 0)

def bandwidth_filter(candidates):
    """对候选节点进行带宽测速，返回按速度降序排列的列表"""
    if not candidates:
        return []

    # 检查 curl 是否可用
    if not shutil.which("curl"):
        print("⚠️ 未检测到 curl 命令，带宽测速将跳过。")
        return []

    print(f"\n开始带宽测速（对前 {len(candidates)} 个节点，并发 {BANDWIDTH_WORKERS}，超时 {BANDWIDTH_TIMEOUT}s）...")
    results = []
    completed = 0
    total = len(candidates)

    with ThreadPoolExecutor(max_workers=BANDWIDTH_WORKERS) as executor:
        futures = {executor.submit(measure_bandwidth_curl, node): node for node in candidates}
        for future in as_completed(futures):
            completed += 1
            node, speed = future.result()
            if speed > 0:
                results.append((node, speed))
            print(f"\r[带宽测速] 进度：{completed}/{total} ({(completed/total)*100:.1f}%)", end="", flush=True)

    print()
    results.sort(key=lambda x: x[1], reverse=True)
    return results

def batch_update_cloudflare_dns(ip_list, ip_info=None, full_bw_results=None, target_count=16):
    """
    将优选 IP 批量更新为 Cloudflare DNS 的同名 A 记录。
    - ip_list: 原 ip.txt 中的纯 IP 列表（用于降级场景）
    - ip_info: 字典，node_str -> 落地IP（用于 IPv6 过滤）
    - full_bw_results: 完整带宽测速结果，格式 [(node_str, speed), ...]，已按速度降序排列
    - target_count: 期望更新的 IP 数量（默认 16）
    """
    if not cfg.get("CF_ENABLED", False):
        print("Cloudflare DNS 批量更新未启用。")
        return

    # 优先使用完整测速结果 + 落地信息来构建更新列表
    dns_ip_list = []
    if full_bw_results and ip_info:
        # 如果需要过滤 IPv6 落地，则按速度顺序挑选落地 IPv4 的节点
        if cfg.get("FILTER_IPV6_AVAILABILITY", False):
            for node_str, speed in full_bw_results:
                returned_ip = ip_info.get(node_str, "")
                if ":" not in returned_ip:   # 落地 IPv4
                    pure_ip = node_str.split(':')[0]
                    dns_ip_list.append(pure_ip)
                if len(dns_ip_list) >= target_count:
                    break
            print(f"从 {len(full_bw_results)} 个测速节点中筛选出 {len(dns_ip_list)} 个落地 IPv4 节点用于 DNS 更新。")
        else:
            # 不过滤 IPv6，直接取前 target_count 个
            for node_str, _ in full_bw_results[:target_count]:
                pure_ip = node_str.split(':')[0]
                dns_ip_list.append(pure_ip)

    # 降级：若上述方法未产生任何 IP，则回退到原 ip_list
    if not dns_ip_list:
        if ip_list:
            print("⚠️ 未能从完整测速结果构建 DNS 列表，降级使用 ip.txt 中的 IP。")
            dns_ip_list = ip_list
        else:
            msg = "没有可用的 IP 用于 DNS 更新，跳过。"
            print(msg)
            send_wxpusher_notification(content=msg, summary="DNS 更新跳过")
            return

    # 去重
    dns_ip_list = list(dict.fromkeys(dns_ip_list))

    print(f"\n准备将以下 {len(dns_ip_list)} 个 IP 批量更新到 Cloudflare DNS: {dns_ip_list}")

    headers = {
        "Authorization": f"Bearer {cfg['CF_API_TOKEN']}",
        "Content-Type": "application/json"
    }
    zone_id = cfg['CF_ZONE_ID']
    record_name = cfg['CF_DNS_RECORD_NAME']
    ttl = cfg.get('CF_TTL', 120)
    proxied = cfg.get('CF_PROXIED', False)

    max_retries = cfg.get('DNS_UPDATE_MAX_RETRIES', 5)
    retry_delay = cfg.get('DNS_UPDATE_RETRY_DELAY', 10)

    for attempt in range(1, max_retries + 1):
        print(f"\n[DNS 更新] 尝试 {attempt}/{max_retries}...")
        try:
            # 查询现有记录
            list_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records?type=A&name={record_name}"
            response = requests.get(list_url, headers=headers)
            response.raise_for_status()
            result = response.json()
            if not result.get('success'):
                error_detail = result.get('errors')
                raise Exception(f"查询 DNS 记录失败: {error_detail}")

            existing_records = result.get('result', [])

            # 构建批量操作
            deletes = [{"id": rec["id"]} for rec in existing_records]
            posts = [
                {
                    "name": record_name,
                    "type": "A",
                    "content": ip,
                    "ttl": ttl,
                    "proxied": proxied
                }
                for ip in dns_ip_list
            ]

            batch_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records/batch"
            payload = {"deletes": deletes, "posts": posts}

            response = requests.post(batch_url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
            if not result.get('success'):
                error_detail = result.get('errors')
                raise Exception(f"批量更新失败: {error_detail}")

            # 成功
            success_msg = f"✅ Cloudflare DNS 批量更新成功！已将 {record_name} 指向 {len(dns_ip_list)} 个 IP。"
            print(success_msg)
            print("   注意：DNS 解析将随机返回这些 IP 中的一个，实现负载均衡。")
            return

        except Exception as e:
            error_msg = f"[尝试 {attempt}/{max_retries}] DNS 更新出错: {e}"
            print(error_msg)
            if attempt < max_retries:
                print(f"等待 {retry_delay} 秒后重试...")
                time.sleep(retry_delay)
            else:
                final_error = f"❌ Cloudflare DNS 更新失败，已重试 {max_retries} 次，错误：{e}"
                print(final_error)
                send_wxpusher_notification(content=final_error, summary="DNS 更新失败")

def sync_to_github():
    """
    根据操作系统调用相应的 Git 同步脚本，支持重试（重试参数从 config.json 读取）。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    if sys.platform == "win32":
        script_name = "git_sync.ps1"
        interpreter = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
        creationflags = subprocess.CREATE_NO_WINDOW
    else:
        script_name = "git_sync.sh"
        interpreter = ["bash"]
        creationflags = 0

    script_path = os.path.join(script_dir, script_name)
    if not os.path.exists(script_path):
        print(f"⚠️ 未找到 {script_name}，跳过 GitHub 同步。")
        return

    # Linux 下确保脚本有执行权限
    if sys.platform != "win32":
        try:
            os.chmod(script_path, 0o755)
        except Exception:
            pass

    max_retries = cfg.get('GITHUB_SYNC_MAX_RETRIES', 5)
    retry_delay = cfg.get('GITHUB_SYNC_RETRY_DELAY', 10)

    for attempt in range(1, max_retries + 1):
        print(f"\n正在同步到 GitHub (尝试 {attempt}/{max_retries})...")
        try:
            cmd = interpreter + [script_path]
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags
            )

            try:
                stdout, stderr = process.communicate(timeout=300)
                if process.returncode == 0:
                    print("✅ 已自动推送到 GitHub。")
                    return
                else:
                    print(f"❌ 推送失败 (退出码 {process.returncode})")
                    if stderr:
                        print(f"错误信息: {stderr.strip()}")
            except subprocess.TimeoutExpired:
                process.kill()
                print("❌ 推送超时（超过5分钟）")
        except Exception as e:
            print(f"❌ 推送过程异常: {e}")

        if attempt < max_retries:
            print(f"等待 {retry_delay} 秒后重试...")
            time.sleep(retry_delay)

    # 所有重试均失败，发送通知
    send_wxpusher_notification(
        content=f"GitHub 推送失败，已重试 {max_retries} 次，请检查网络或仓库状态。",
        summary="GitHub 推送失败"
    )
    print(f"⚠️ 已尝试 {max_retries} 次推送，均失败，请检查网络或 GitHub 仓库状态。")

def main():
    mode_str = f"全局最优{GLOBAL_TOP_N}个" if USE_GLOBAL_MODE else f"每个国家最优{PER_COUNTRY_TOP_N}个"
    print(f"当前模式：{mode_str}，每个节点测试 {TCP_PROBES} 次 TCP 连接")
    print(f"最低成功率要求：{MIN_SUCCESS_RATE*100:.0f}%")
    print(f"IP 可用性二次筛选：{'启用' if TEST_AVAILABILITY else '禁用'}（仅对候选节点）")
    print(f"IPv6 客户端 IP 过滤（仅作用于DNS更新环节）：{'启用' if FILTER_IPV6_AVAILABILITY else '禁用'}")
    print(f"带宽测速候选数：{BANDWIDTH_CANDIDATES}，测速文件大小：{BANDWIDTH_SIZE_MB} MB，超时：{BANDWIDTH_TIMEOUT}s")
    if FILTER_COUNTRIES_ENABLED:
        print(f"国家过滤：启用，允许国家：{', '.join(ALLOWED_COUNTRIES)}")

    # 1. 获取所有节点
    nodes = fetch_nodes()
    if not nodes:
        print("没有获取到任何有效节点，退出。")
        sys.exit(1)

    # 优化：在 TCP 测试前进行国家过滤，大幅减少测试量
    if FILTER_COUNTRIES_ENABLED and ALLOWED_COUNTRIES:
        before = len(nodes)
        allowed_set = {c.upper() for c in ALLOWED_COUNTRIES}
        filtered_nodes = []
        for node in nodes:
            parts = node.split('#')
            if len(parts) == 2 and parts[1].upper() in allowed_set:
                filtered_nodes.append(node)
        nodes = filtered_nodes
        after = len(nodes)
        print(f"\n国家过滤（测试前）：{before} -> {after} 个节点（允许国家：{', '.join(allowed_set)}）")
        if not nodes:
            print("⚠️ 过滤后无任何节点，退出程序。")
            sys.exit(0)

    total = len(nodes)
    print(f"开始 TCP 连接测试（超时 {TIMEOUT}s，并发 {MAX_WORKERS}）...")

    # 2. 并发 TCP 测试
    results = []
    completed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(test_node, node): node for node in nodes}
        for future in as_completed(futures):
            completed += 1
            res = future.result()
            if res:
                results.append(res)
            print(f"\r进度：{completed}/{total} ({(completed/total)*100:.1f}%)", end="", flush=True)

    print("\nTCP 测试完成！")
    if not results:
        print("没有通过成功率筛选的节点，请检查网络或降低 MIN_SUCCESS_RATE。")
        sys.exit(0)

    # 3. 排序：优先按成功率降序，相同成功率再按延迟升序
    results.sort(key=lambda x: (-x[3], x[1]))

    # 4. 选出候选节点
    if USE_GLOBAL_MODE:
        candidates = [node for node, _, _, _ in results[:BANDWIDTH_CANDIDATES]]
        print(f"\nTCP 最优前 {len(candidates)} 个节点进入候选池：")
        for i, (node, lat, country, succ) in enumerate(results[:BANDWIDTH_CANDIDATES], 1):
            rate = succ / TCP_PROBES * 100
            print(f"  {i}. {node} 成功率 {rate:.0f}% 最小延迟 {lat*1000:.2f}ms")
    else:
        country_best = {}
        for node_str, lat, country, succ in results:
            if country not in country_best:
                country_best[country] = (node_str, lat, succ)
        country_list = sorted(country_best.values(), key=lambda x: (-x[2], x[1]))
        candidates = [node for node, _, _ in country_list[:BANDWIDTH_CANDIDATES]]
        print(f"\n各国家最优节点共 {len(country_list)} 个，取前 {len(candidates)} 个进入候选池：")
        for i, (node, lat, succ) in enumerate(country_list[:BANDWIDTH_CANDIDATES], 1):
            rate = succ / TCP_PROBES * 100
            print(f"  {i}. {node} 成功率 {rate:.0f}% 最小延迟 {lat*1000:.2f}ms")

    if not candidates:
        print("没有候选节点，退出。")
        sys.exit(0)

    # 5. IP 可用性二次筛选（仅对候选节点）
    candidates_after_availability, avail_ip_info = availability_filter_candidates(candidates)

    # 6. 带宽测速
    bw_results = bandwidth_filter(candidates_after_availability)

    # 7. 确定最终节点
    if bw_results:
        if USE_GLOBAL_MODE:
            final_selected = [node for node, _ in bw_results[:GLOBAL_TOP_N]]
        else:
            final_selected = [node for node, _ in bw_results[:PER_COUNTRY_TOP_N]]

        print("\n================ 最终优选节点（基于带宽测速）================")
        for i, (node, speed) in enumerate(bw_results[:len(final_selected)], 1):
            print(f"{i}. {node} 速度 {speed:.2f} Mbps")
    else:
        print("\n⚠️ 带宽测速无有效结果，将使用 TCP 筛选结果作为最终节点。")
        if USE_GLOBAL_MODE:
            final_selected = [node for node, _, _, _ in results[:GLOBAL_TOP_N]]
        else:
            final_selected = [node for node, _, _ in country_list[:PER_COUNTRY_TOP_N]]

    # 8. 保存结果
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for node_str in final_selected:
            f.write(node_str + "\n")
    print(f"\n结果已保存到 {OUTPUT_FILE}（共 {len(final_selected)} 个节点）")

    # 9. 读取 ip.txt 中的纯 IP 列表，用于 DNS 更新（作为降级备用）
    ip_list = []
    try:
        with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
            ip_list = [line.split(':')[0].strip() for line in f if line.strip()]
    except Exception as e:
        print(f"读取 {OUTPUT_FILE} 时发生错误: {e}")

    # 10. 批量更新 Cloudflare DNS（如果启用）
    # 传递完整测速结果和落地信息，以便从候选池中优选 IPv4 节点
    target_dns_count = GLOBAL_TOP_N if USE_GLOBAL_MODE else PER_COUNTRY_TOP_N
    batch_update_cloudflare_dns(
        ip_list,
        ip_info=avail_ip_info,
        full_bw_results=bw_results,
        target_count=target_dns_count
    )

    # 11. 同步到 GitHub（保留原有功能）
    sync_to_github()

if __name__ == "__main__":
    main()
