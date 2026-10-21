---
name: uptime-kuma-heartbeats
description: 心跳与统计。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行心跳与统计相关操作时使用。
---

# 心跳与统计

查询心跳、延迟、可用率及证书信息。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_heartbeats` | 读 | — |
| `get_important_heartbeats` | 读 | — |
| `avg_ping` | 读 | — |
| `uptime` | 读 | — |
| `cert_info` | 读 | — |

## 操作要点

`get_heartbeats` 返回按监控 ID 分组的映射；单条记录可能使用 `monitor_id` 或 `monitorID`。比较时间前统一时区。
