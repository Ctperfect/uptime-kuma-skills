# uptime-kuma-skills

本项目提供 Uptime Kuma 的 CLI、Python 客户端和 Codex 技能说明。它是基于
[lucasheld/uptime-kuma-api](https://github.com/lucasheld/uptime-kuma-api) 开发的技能扩展，
通过该项目提供的 `uptime_kuma_api` Python 库调用 Uptime Kuma API；本技能集不属于上游库本身。
Python 包名使用 `uptime_kuma_skills`，由仓库根目录的兼容入口转发。
当前有 11 个模块、86 个操作；完整清单以
`python -m uptime_kuma_skills list --json` 的实时输出为准。

需要 Python 3.10 或更新版本。从仓库根目录安装底层 API 库依赖：

```powershell
python -m pip install -r requirements.txt
```

Python 兼容入口 `uptime_kuma_skills.py` 与本项目源码位于仓库根目录；从该目录运行本文中的 CLI 命令。

## CLI

```powershell
# 离线查看操作及参数
python -m uptime_kuma_skills list --json
python -m uptime_kuma_skills describe add_monitor --json

# 查询实例
python -m uptime_kuma_skills --url <实例地址> --username <账号> --password <密码> get_monitors

# 写入前预览：不连接实例
python -m uptime_kuma_skills --dry-run add_monitor --type http --name Example --set url=https://example.com

# 确认目标与参数后执行
python -m uptime_kuma_skills --url <实例地址> --username <账号> --password <密码> add_monitor --type http --name Example --set url=https://example.com --yes
```

`--url` 等连接参数与操作参数同名时，操作参数使用 `--set key=value`。例如监控地址用
`--set url=https://example.com`，代理账号用 `--set username=...`。复杂对象可用
`call <操作> --params '<JSON对象>'`，也可使用 Python 客户端。全局连接参数、`--yes`、
`--dry-run`、`--pretty` 可放在子命令前后。

| effect | CLI 行为 |
| --- | --- |
| `read` | 直接执行 |
| `write` | 要求 `--yes`，或用 `--dry-run` 离线预览 |
| `forbidden` | 始终拒绝执行 |

退出码：`0` 成功、`1` 参数错误、`2` 连接/认证/服务端错误、`3` 禁止操作、
`4` 写操作缺少 `--yes`。

CLI 默认递归遮蔽已知凭据字段及 URL 中的常见密钥参数；`--no-redact` 显式输出原文。
脱敏不能保证识别任意自定义字段或服务端消息中的秘密，保存或转发结果前仍需检查。
命令行上的密码可能被本机进程列表或终端历史记录看到，按目标环境的凭据管理方式传入。

## 致谢

本技能集基于 [Lucas Held 的 `uptime-kuma-api`](https://github.com/lucasheld/uptime-kuma-api) 构建，
感谢 Lucas Held 开发并维护上游 API 客户端。本仓库是独立的技能扩展，并非上游项目的官方发布。

## Python

```python
from uptime_kuma_skills import UptimeKumaSkills, get_operation
from uptime_kuma_skills.redact import redact

with UptimeKumaSkills(URL, USERNAME, PASSWORD) as client:
    print(redact(client.get_monitors()))
    print(get_operation("add_monitor").effect.value)
    # 已授权的连续写入可在同一会话中调用 client.invoke(...)
```

`UptimeKumaSkills(url, username=None, password=None, token="", timeout=10,
ssl_verify=True, auto_setup=False)` 在创建时连接并登录。`auto_setup` 默认关闭，避免
连到未初始化实例时意外创建管理员。只读操作在断线后允许重连重试；写操作不会自动重放。

Python 客户端的返回值**未经脱敏**，且**不执行 CLI 的 effect 闸门**。调用方应先核对操作
的 `effect` 和实例规则，再使用 `redact` 处理将展示或保存的结果。可通过 `client.api`
访问原始底层 API；这同样绕过 CLI 闸门。

每次 CLI 命令都会重新登录。需要连续执行「查询→修改→回读」时用单个 Python 进程，
以避免触发实例登录限流。新登录和写入后的事件快照可能滞后，回读应有界重试。

## 维护与验证

```powershell
python -m compileall -q .
python -m uptime_kuma_skills.selftest
python -m uptime_kuma_skills.scripts.generate_docs
```

11 个模块的技能页由最后一条命令从操作注册表生成；修改注册表后重建并运行离线回归。
`selftest` 不联网。`selftest_live` 仅在明确指定目标且使用 `--live` 时自建自毁；
仓库原有 `tests/` 是清空目标数据的破坏性套件，绝不能指向生产实例。

Codex 入口见 [SKILL.md](SKILL.md)，按资源选择对应的 `skills/<模块>/SKILL.md`。
