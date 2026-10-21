"""从操作注册表重建模块技能入口：python -m uptime_kuma_skills.scripts.generate_docs。"""

from pathlib import Path

from uptime_kuma_skills.registry import MODULE_OPERATIONS, Effect, list_operations


# 只维护会改变操作决策的模块提示；参数和副作用等级由注册表生成。
MODULE_GUIDANCE = {
    "auth": ("身份认证与会话", "登录、初始化、双因素认证及会话操作。",
             "统一客户端会自动登录。`setup` 会创建管理员；仅在明确选中的未初始化实例上使用。"),
    "monitors": ("监控项管理", "查询和管理监控、分组、状态及标签关联。",
                 "新登录或写入后快照可能滞后；按 ID 和名称回读并有界重试。心跳空列表不能证明监控不存在。新增监控前明确 `parent` 和 `notificationIDList`。"),
    "status-pages": ("状态页管理", "管理状态页和故障公告。",
                     "修改前按 slug 读取现状；保留已有发布状态和监控选择，写后按 slug 回读。"),
    "notifications": ("通知渠道管理", "管理通知渠道及 Apprise 可用性。",
                      "新增通知的必填字段随 `type` 变化，先看 `describe add_notification --json`。新增时明确 `isDefault` 和 `applyExisting`，避免把渠道应用到现有监控。`edit_notification` 只要求 `id_`，其他字段继承现值。"),
    "heartbeats": ("心跳与统计", "查询心跳、延迟、可用率及证书信息。",
                   "`get_heartbeats` 返回按监控 ID 分组的映射；单条记录可能使用 `monitor_id` 或 `monitorID`。比较时间前统一时区。"),
    "tags": ("标签管理", "查询和管理标签。",
             "删除或编辑标签前先读取标签 ID 及其监控关联。"),
    "proxies": ("代理管理", "查询和管理代理配置。",
                "操作参数 `username`、`password` 与连接参数重名，CLI 用 `--set username=...`、`--set password=...`。"),
    "maintenances": ("维护计划管理", "管理维护计划及其监控和状态页关联。",
                       "先读取关联对象；创建时使用 `timezoneOption`，具体策略参数以 `describe` 为准。"),
    "api-keys": ("API Key 管理", "查询、创建和删除 API Key。",
                 "创建返回的 `key` 仅出现一次，CLI 默认会遮蔽它；确需取得原文时在创建命令上显式使用 `--no-redact` 并安全保存。现有 Key 可能被外部自动化使用，删除前确认归属。"),
    "docker-hosts": ("Docker 主机管理", "查询和管理 Docker 主机。",
                     "测试 Docker 主机会连接外部目标；CLI 将 `test_docker_host` 标为禁止。"),
    "system": ("系统信息与设置", "查询版本、实例信息、设置和数据库大小。",
               "全局设置、备份导入、清理历史和缩库会影响整个实例；CLI 将这些操作标为禁止。"),
}


def render_module_doc(module: str) -> str:
    title, scope, note = MODULE_GUIDANCE[module]
    operations = list_operations(module)
    lines = [
        "---",
        f"name: uptime-kuma-{module}",
        f"description: {title}。当需要通过 uptime_kuma_skills 对 Uptime Kuma 实例执行{title}相关操作时使用。",
        "---",
        "",
        f"# {title}",
        "",
        scope,
        "",
        "先读 [统一入口与安全约定](../../SKILL.md)。参数、枚举和条件必填以",
        "`python -m uptime_kuma_skills describe <操作> --json` 为准。",
        "",
        "## 操作",
        "",
        "| 操作 | 副作用 | 必填参数 |",
        "| --- | --- | --- |",
    ]
    for op in operations:
        required = ", ".join(p.name for p in op.params if p.required) or "—"
        if any(p.required_if for p in op.params):
            required += "；另有条件必填"
        effect = {Effect.READ: "读", Effect.WRITE: "写（CLI 需 `--yes`）",
                  Effect.FORBIDDEN: "CLI 禁止"}[op.effect]
        lines.append(f"| `{op.name}` | {effect} | {required} |")
    lines += [
        "",
        "## 操作要点",
        "",
        note,
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "skills"
    for module in MODULE_OPERATIONS:
        path = root / module / "SKILL.md"
        path.write_text(render_module_doc(module), encoding="utf-8", newline="\n")
        print(path)


if __name__ == "__main__":
    main()
