---
name: uptime-kuma-proxies
description: 代理管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行代理管理相关操作时使用。
---

# 代理管理

查询和管理代理配置。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_proxies` | 读 | — |
| `get_proxy` | 读 | id_ |
| `add_proxy` | 写（CLI 需 `--yes`） | protocol, host, port |
| `edit_proxy` | 写（CLI 需 `--yes`） | id_ |
| `delete_proxy` | 写（CLI 需 `--yes`） | id_ |

## 操作要点

操作参数 `username`、`password` 与连接参数重名，CLI 用 `--set username=...`、`--set password=...`。
