---
name: uptime-kuma-notifications
description: 通知渠道管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行通知渠道管理相关操作时使用。
---

# 通知渠道管理

管理通知渠道及 Apprise 可用性。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_notifications` | 读 | — |
| `get_notification` | 读 | id_ |
| `add_notification` | 写（CLI 需 `--yes`） | name, type；另有条件必填 |
| `edit_notification` | 写（CLI 需 `--yes`） | id_ |
| `delete_notification` | 写（CLI 需 `--yes`） | id_ |
| `test_notification` | CLI 禁止 | name, type；另有条件必填 |
| `check_apprise` | 读 | — |

## 操作要点

新增通知的必填字段随 `type` 变化，先看 `describe add_notification --json`。新增时明确 `isDefault` 和 `applyExisting`，避免把渠道应用到现有监控。`edit_notification` 只要求 `id_`，其他字段继承现值。
