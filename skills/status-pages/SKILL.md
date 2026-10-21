---
name: uptime-kuma-status-pages
description: 状态页管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行状态页管理相关操作时使用。
---

# 状态页管理

管理状态页和故障公告。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_status_pages` | 读 | — |
| `get_status_page` | 读 | slug |
| `add_status_page` | 写（CLI 需 `--yes`） | slug, title |
| `delete_status_page` | 写（CLI 需 `--yes`） | slug |
| `save_status_page` | 写（CLI 需 `--yes`） | slug, title |
| `post_incident` | 写（CLI 需 `--yes`） | slug, title, content |
| `unpin_incident` | 写（CLI 需 `--yes`） | slug |

## 操作要点

修改前按 slug 读取现状；保留已有发布状态和监控选择，写后按 slug 回读。
