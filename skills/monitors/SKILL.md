---
name: uptime-kuma-monitors
description: 监控项管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行监控项管理相关操作时使用。
---

# 监控项管理

查询和管理监控、分组、状态及标签关联。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_monitors` | 读 | — |
| `get_monitor` | 读 | id_ |
| `add_monitor` | 写（CLI 需 `--yes`） | type, name；另有条件必填 |
| `edit_monitor` | 写（CLI 需 `--yes`） | id_ |
| `delete_monitor` | 写（CLI 需 `--yes`） | id_ |
| `pause_monitor` | 写（CLI 需 `--yes`） | id_ |
| `resume_monitor` | 写（CLI 需 `--yes`） | id_ |
| `get_monitor_beats` | 读 | id_, hours |
| `get_monitor_status` | 读 | monitor_id |
| `get_game_list` | 读 | — |
| `test_chrome` | CLI 禁止 | executable |
| `add_monitor_tag` | 写（CLI 需 `--yes`） | tag_id, monitor_id |
| `delete_monitor_tag` | 写（CLI 需 `--yes`） | tag_id, monitor_id |

## 操作要点

新登录或写入后快照可能滞后；按 ID 和名称回读并有界重试。心跳空列表不能证明监控不存在。新增监控前明确 `parent` 和 `notificationIDList`。
