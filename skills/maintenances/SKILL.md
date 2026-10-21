---
name: uptime-kuma-maintenances
description: 维护计划管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行维护计划管理相关操作时使用。
---

# 维护计划管理

管理维护计划及其监控和状态页关联。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_maintenances` | 读 | — |
| `get_maintenance` | 读 | id_ |
| `add_maintenance` | 写（CLI 需 `--yes`） | title, strategy |
| `edit_maintenance` | 写（CLI 需 `--yes`） | id_ |
| `delete_maintenance` | 写（CLI 需 `--yes`） | id_ |
| `pause_maintenance` | 写（CLI 需 `--yes`） | id_ |
| `resume_maintenance` | 写（CLI 需 `--yes`） | id_ |
| `get_monitor_maintenance` | 读 | id_ |
| `add_monitor_maintenance` | 写（CLI 需 `--yes`） | id_, monitors |
| `get_status_page_maintenance` | 读 | id_ |
| `add_status_page_maintenance` | 写（CLI 需 `--yes`） | id_, status_pages |

## 操作要点

先读取关联对象；创建时使用 `timezoneOption`，具体策略参数以 `describe` 为准。
