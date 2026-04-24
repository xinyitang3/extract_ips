import json
import csv
import argparse
import os
import sys

def extract_ips_from_json(file_path):
    """从JSON文件中提取所有ip"""
    ips = []
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        for bucket in data.get('buckets', []):
            ip = bucket.get('key')
            if ip:
                ips.append(ip)
    return ips

def extract_ips_from_csv(file_path):
    """从CSV文件中提取ip列的所有值"""
    ips = []
    with open(file_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            ip = row.get('ip')
            if ip:
                ips.append(ip)
    return ips

def main():
    parser = argparse.ArgumentParser(description='从JSON或CSV文件中提取IP地址')
    parser.add_argument('files', nargs='*', default=['1.txt', '1.csv'],
                        help='要处理的文件，默认: 1.txt 1.csv')
    parser.add_argument('-o', '--output', default='ip.txt',
                        help='输出文件名，默认: ip.txt')
    args = parser.parse_args()

    # 如果没有提供任何文件，且默认文件也不存在，提示用户
    if not args.files:
        print("错误：未指定输入文件，且没有默认文件。", file=sys.stderr)
        sys.exit(1)

    all_ips = []
    for file_path in args.files:
        if not os.path.exists(file_path):
            print(f"警告: 文件不存在，跳过: {file_path}", file=sys.stderr)
            continue

        # 根据扩展名判断解析方式，也允许 .txt 为 JSON
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == '.json' or file_path.endswith('.txt'):  # 支持 1.txt 这种 JSON 文件
                ips = extract_ips_from_json(file_path)
                print(f"从 {file_path} 提取到 {len(ips)} 个IP (JSON模式)")
            elif ext == '.csv':
                ips = extract_ips_from_csv(file_path)
                print(f"从 {file_path} 提取到 {len(ips)} 个IP (CSV模式)")
            else:
                print(f"警告: 不支持的文件类型，跳过: {file_path}", file=sys.stderr)
                continue
            all_ips.extend(ips)
        except Exception as e:
            print(f"错误: 处理文件 {file_path} 时出错: {e}", file=sys.stderr)

    # 去重（保持首次出现顺序）
    unique_ips = list(dict.fromkeys(all_ips))

    # 写入输出文件
    with open(args.output, 'w', encoding='utf-8') as f:
        for ip in unique_ips:
            f.write(ip + '\n')

    print(f"完成。去重后共 {len(unique_ips)} 个IP，已写入 {args.output}")

if __name__ == '__main__':
    main()