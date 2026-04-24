# extract_ips

从 Censys 或 FOFA 导出的 JSON / CSV 文件中提取所有 IP 地址，输出去重后的 IP 列表。

## 功能特点

- 支持 Censys 导出的 JSON 文件（或保存为 `.txt` 后缀的 JSON 文件）和 FOFA 导出的 CSV 文件
- 自动识别文件类型：
  - JSON（含 `.txt` 后缀）：提取 `buckets` 数组内每个对象的 `key` 字段
  - CSV：提取 `ip` 列的所有值
- 一次可处理多个文件，自动合并结果
- 去重并保持首次出现顺序
- 自定义输出文件（默认 `ip.txt`）

## 默认文件说明

如果运行时未指定任何文件，脚本会自动查找当前目录下的 `1.txt` 和 `1.csv`。这两个文件可直接从以下平台导出获得：

- **1.txt** —— 来自 [Censys](https://censys.io/) 的 JSON 导出  
  将 Censys 的查询结果导出为 JSON 格式，重命名为 `1.txt` 即可直接使用。
- **1.csv** —— 来自 [FOFA](https://fofa.info/) 的 CSV 导出  
  在 FOFA 中将结果导出为 CSV（需包含 `ip` 列），命名为 `1.csv` 即可直接使用。

> 你也可以指定其他文件，只要格式满足下方要求即可。

## 环境要求

- Python 3.6 及以上
- 无需安装第三方依赖（仅使用 Python 标准库）

## 使用方法

```bash
python extract_ips.py [文件...] [-o 输出文件]
```

如果不提供任何文件，程序会尝试处理当前目录下的默认文件 `1.txt` 和 `1.csv`。

### 参数说明

| 参数 | 说明 |
|------|------|
| `files` | 要处理的文件路径，可指定多个，用空格分隔。支持 `.json`、`.txt`（按 JSON 处理）、`.csv` |
| `-o, --output` | 指定输出文件，默认 `ip.txt` |

## 示例

使用默认的 Censys 和 FOFA 文件（需先准备好 `1.txt` 和 `1.csv`）：

```bash
python extract_ips.py
```

单独处理一个 Censys JSON 文件：

```bash
python extract_ips.py censys_export.txt -o ips.txt
```

同时处理多个文件：

```bash
python extract_ips.py result.json fofa_result.csv
```

## 输入文件格式要求

### Censys JSON（可保存为 `.txt`）

顶层对象必须包含 `buckets` 数组，数组元素需有 `key` 字段，示例：

```json
{
  "buckets": [
    {"key": "192.168.1.1"},
    {"key": "10.0.0.1"}
  ]
}
```

### FOFA CSV

必须包含 `ip` 列（列名需为英文小写 `ip`），示例：

```csv
host,ip,port
example.com,192.168.1.1,8080
test.org,10.0.0.1,443
```

## 输出

- 每行一个提取到的 IP，写入指定的输出文件
- 文本编码为 UTF-8，无 BOM
- 会对所有来源的 IP 进行去重，保留首次出现的顺序

## 错误处理

- 文件不存在：输出警告并跳过
- 文件类型不支持：跳过并提示
- 解析出错：打印错误信息并继续处理其他文件

## 许可证

MIT License
