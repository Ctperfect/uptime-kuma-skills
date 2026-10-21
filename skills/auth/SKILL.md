---
name: uptime-kuma-auth
description: 身份认证与会话。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行身份认证与会话相关操作时使用。
---

# 身份认证与会话

登录、初始化、双因素认证及会话操作。

先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以
`python -m uptime_kuma_skills describe <操作> --json` 为准。

## 操作

| 操作 | 副作用 | 必填参数 |
| --- | --- | --- |
| `login` | 写（CLI 需 `--yes`） | — |
| `login_by_token` | 写（CLI 需 `--yes`） | token |
| `logout` | 写（CLI 需 `--yes`） | — |
| `need_setup` | 读 | — |
| `setup` | 写（CLI 需 `--yes`） | username, password |
| `change_password` | CLI 禁止 | old_password, new_password |
| `twofa_status` | 读 | — |
| `prepare_2fa` | 写（CLI 需 `--yes`） | password |
| `verify_token` | 写（CLI 需 `--yes`） | token, password |
| `save_2fa` | 写（CLI 需 `--yes`） | password |
| `disable_2fa` | 写（CLI 需 `--yes`） | password |

## 操作要点

统一客户端会自动登录。`setup` 会创建管理员；仅在明确选中的未初始化实例上使用。
