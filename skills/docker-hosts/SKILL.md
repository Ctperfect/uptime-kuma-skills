---
name: uptime-kuma-docker-hosts
description: Docker 主机管理。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行Docker 主机管理相关操作时使用。
---

# Docker 主机管理

查询和管理 Docker 主机。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `get_docker_hosts` | 读 | — |
| `get_docker_host` | 读 | id_ |
| `add_docker_host` | 写（CLI 需 `--yes`） | name, dockerType |
| `edit_docker_host` | 写（CLI 需 `--yes`） | id_ |
| `delete_docker_host` | 写（CLI 需 `--yes`） | id_ |
| `test_docker_host` | CLI 禁止 | name, dockerType |

## 操作要点

测试 Docker 主机会连接外部目标；CLI 将 `test_docker_host` 标为禁止。
