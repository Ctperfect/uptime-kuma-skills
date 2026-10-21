---
name: uptime-kuma-tags
description: 标签管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行标签管理相关操作时使用。
---

# 标签管理

查询和管理标签。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_tags` | 读 | — |
| `get_tag` | 读 | id_ |
| `add_tag` | 写（CLI 需 `--yes`） | name, color |
| `edit_tag` | 写（CLI 需 `--yes`） | id_ |
| `delete_tag` | 写（CLI 需 `--yes`） | id_ |

## 操作要点

删除或编辑标签前先读取标签 ID 及其监控关联。
