---
name: uptime-kuma-system
description: 系统信息与设置。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行系统信息与设置相关操作时使用。
---

# 系统信息与设置

查询版本、实例信息、设置和数据库大小。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `version` | 读 | — |
| `info` | 读 | — |
| `get_settings` | 读 | — |
| `set_settings` | CLI 禁止 | — |
| `get_database_size` | 读 | — |
| `shrink_database` | CLI 禁止 | — |
| `upload_backup` | CLI 禁止 | json_data |
| `clear_events` | CLI 禁止 | monitor_id |
| `clear_heartbeats` | CLI 禁止 | monitor_id |
| `clear_statistics` | CLI 禁止 | — |

## 操作要点

全局设置、备份导入、清理历史和缩库会影响整个实例；CLI 将这些操作标为禁止。
