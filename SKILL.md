---
name: uptime-kuma-skills
description: 通过本仓库的 CLI 或 Python 客户端查询、管理 Uptime Kuma 实例的监控、通知、状态页及系统资源。需要操作 Uptime Kuma 实例时使用。
---

# Uptime Kuma 实例操作

本技能目录提供 Uptime Kuma 的运维入口，是基于
[lucasheld/uptime-kuma-api](https://github.com/lucasheld/uptime-kuma-api) 开发的技能扩展，
通过 Python 包 `uptime_kuma_skills` 调用该上游项目提供的 `uptime_kuma_api`。
先确定目标实例与操作名，再用
`python -m uptime_kuma_skills describe <操作> --json` 查看实际参数、条件必填和 `effect`。
完整操作清单可用 `python -m uptime_kuma_skills list --json` 查询。

## 执行

- 查询：`python -m uptime_kuma_skills --url <实例> --username <用户> --password <密码> get_monitors`
- 写入预览：`python -m uptime_kuma_skills --dry-run add_monitor --type http --name Example --set url=https://example.com`
- 写入执行：在目标与参数确认后，对同一命令加连接参数和 `--yes`。

`url`、`timeout`、`username`、`password`、`token` 与连接参数重名时，操作参数用
`--set key=value` 传入；复杂列表和对象用 `call <操作> --params '<JSON对象>'`。
全局参数和 `--dry-run`、`--yes` 可放在子命令前后。`--dry-run` 只解析并打印，不连接实例。

CLI 将操作标为 `read`、`write` 或 `forbidden`。`write` 需 `--yes`；`forbidden` 在 CLI
中始终拒绝。返回值默认按已知敏感字段及 URL 中的常见凭据脱敏；`--no-redact` 会输出原文。
CLI 的错误码：`0` 成功、`1` 参数错误、`2` 服务端或连接错误、`3` 禁止操作、`4` 缺少 `--yes`。

Python 入口 `UptimeKumaSkills(url, username, password)` 复用单一会话，适合连续查询或
经授权的连续修改。**Python 返回原始值，也不执行 CLI 的写入闸门。**使用 Python 修改实例前，
按 `effect` 和目标实例规则核对操作；展示或保存结果时主动调用 `redact`。
每次 CLI 调用都会重新登录；连续操作优先用单个 Python 进程，避免实例登录限流。

## 按资源查看

只有当前任务涉及的模块才需要读取：

| 资源 | 模块技能 |
| --- | --- |
| 登录与双因素认证 | [auth](skills/auth/SKILL.md) |
| 监控、分组与标签关联 | [monitors](skills/monitors/SKILL.md) |
| 状态页与故障公告 | [status-pages](skills/status-pages/SKILL.md) |
| 通知渠道 | [notifications](skills/notifications/SKILL.md) |
| 心跳、延迟、可用率 | [heartbeats](skills/heartbeats/SKILL.md) |
| 标签 | [tags](skills/tags/SKILL.md) |
| 代理 | [proxies](skills/proxies/SKILL.md) |
| 维护计划 | [maintenances](skills/maintenances/SKILL.md) |
| API Key | [api-keys](skills/api-keys/SKILL.md) |
| Docker 主机 | [docker-hosts](skills/docker-hosts/SKILL.md) |
| 实例信息与系统设置 | [system](skills/system/SKILL.md) |

代码接口和离线验证见 [README.md](README.md)。在本仓库连接生产实例时，还须遵守根目录
`AGENTS.md` 中的对象隔离、回收及禁止操作规则。
