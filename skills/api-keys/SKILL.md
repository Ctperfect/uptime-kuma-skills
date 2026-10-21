---
name: uptime-kuma-api-keys
description: API Key 管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行API Key 管理相关操作时使用。
---

# API Key 管理

查询、创建和删除 API Key。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_api_keys` | 读 | — |
| `get_api_key` | 读 | id_ |
| `add_api_key` | 写（CLI 需 `--yes`） | name, expires, active |
| `enable_api_key` | CLI 禁止 | id_ |
| `disable_api_key` | CLI 禁止 | id_ |
| `delete_api_key` | 写（CLI 需 `--yes`） | id_ |

## 操作要点

创建返回的 `key` 仅出现一次，CLI 默认会遮蔽它；确需取得原文时在创建命令上显式使用 `--no-redact` 并安全保存。现有 Key 可能被外部自动化使用，删除前确认归属。
