"""命令行入口。

统一约定：全局传入 ``--url`` / ``--username`` / ``--password`` 三个基础参数即可
自动完成鉴权，然后执行任意操作。支持四种用法：

* ``list`` / ``describe``：离线查看操作清单与参数详情（无需连接）
* ``call <operation>``：通用调用，参数用 ``--set key=value`` 或 ``--params <json>`` 传入
* ``<operation>``：为每个操作生成的便捷子命令，参数以 ``--key value`` 形式暴露
* ``--json``：把 ``list`` / ``describe`` 的输出变成机器可读结构

安全约定（默认安全，需显式放开）：

* 返回结果**默认脱敏**，凭据字段显示为 ``***``；确需原文用 ``--no-redact``。
* 写操作**默认拦截**，需 ``--yes``；``--dry-run`` 只预览、绝不写入。
* ``FORBIDDEN`` 等级的操作（清空历史、改密码、缩库、覆盖导入、向真实渠道发消息等）
  一律硬性拒绝，``--yes`` 也不能放行。
"""

import argparse
import difflib
import json
import sys

from uptime_kuma_api import UptimeKumaException, Timeout

from .client import UptimeKumaSkills
from .operations import coerce_params, normalize_result
from .redact import redact, redacted_fields
from .registry import (
    OPERATIONS,
    Effect,
    cli_flag_for,
    describe_all,
    describe_operation,
    list_operations,
    missing_required,
)

PROG = "uptime-kuma-skills"

def _add_gate_args(parser: argparse.ArgumentParser) -> None:
    """把闸门与输出开关同时挂到主解析器与每个子命令上。

    这样 ``--yes`` 放在子命令**前**或**后**都能生效（旧版全局参数只能在前，是个坑）。
    未指定时用 ``argparse.SUPPRESS``，防止子解析器的默认值覆盖前置开关。
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--redact", dest="redact", action="store_true", default=argparse.SUPPRESS,
                       help="输出中遮蔽凭据字段（默认行为）")
    group.add_argument("--no-redact", dest="redact", action="store_false", default=argparse.SUPPRESS,
                       help="输出原始值，不遮蔽凭据（谨慎使用）")
    parser.add_argument("--yes", dest="yes", action="store_true", default=argparse.SUPPRESS,
                        help="确认执行有副作用的写操作")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=argparse.SUPPRESS,
                        help="只打印将要执行的操作与参数，不做任何写入")
    parser.add_argument("--auto-setup", dest="auto_setup", action="store_true",
                        default=argparse.SUPPRESS,
                        help="允许在未初始化的实例上自动创建管理员账号。"
                             "默认**关闭**：URL 打错时自动 setup 会凭空建出一个管理员账号。")

def _add_pure_global_args(parser: argparse.ArgumentParser) -> None:
    """只注册"连接类"全局参数（不含闸门/输出开关，那些由 _add_gate_args 负责）。

    这些参数存储在 ``_conn_*`` 命名空间下，与操作参数（存于 ``args.<参数名>``）
    **物理隔离**。这一点是必须的：``add_monitor`` 自身也有一个 ``url`` 参数，
    若两者共用 ``dest="url"``，则 ``add_monitor --monitor-url A --url B``
    会让连接地址覆盖监控地址，酿成难以察觉的错误配置（实测已被覆盖过一次）。
    """
    parser.add_argument("--url", dest="_conn_url", default=argparse.SUPPRESS,
                        help="Uptime Kuma 实例地址，例如 https://uptime.example.com/")
    parser.add_argument("--username", dest="_conn_username", default=argparse.SUPPRESS,
                        help="登录账号")
    parser.add_argument("--password", dest="_conn_password", default=argparse.SUPPRESS,
                        help="登录密码")
    parser.add_argument("--token", dest="_conn_token", default=argparse.SUPPRESS,
                        help="可选：已有登录 token")
    parser.add_argument("--timeout", dest="_conn_timeout", type=float,
                        default=argparse.SUPPRESS,
                        help="连接/响应超时（秒），默认 10")
    parser.add_argument(
        "--no-ssl-verify", dest="_conn_ssl_verify", action="store_false",
        default=argparse.SUPPRESS,
        help="跳过 SSL 证书校验（自签证书实例使用）",
    )


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pretty", action="store_true", default=argparse.SUPPRESS,
                        help="美化 JSON 输出")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        default=argparse.SUPPRESS,
                        help="以机器可读 JSON 输出 list / describe 的结果")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Uptime Kuma 技能集统一命令行入口：传入地址/账号/密码即可执行任意操作。",
    )
    _add_pure_global_args(parser)
    _add_output_args(parser)
    _add_gate_args(parser)
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出全部操作（可按模块过滤）")
    p_list.add_argument("--module", help="仅列出指定模块的操作")
    _add_output_args(p_list)

    p_desc = sub.add_parser("describe", help="查看某个操作的说明与参数")
    p_desc.add_argument("operation", help="操作名")
    _add_output_args(p_desc)

    p_call = sub.add_parser("call", help="通用调用任意操作")
    p_call.add_argument("operation", help="操作名")
    p_call.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="设置参数，可重复使用")
    p_call.add_argument("--params", default=None, help="以 JSON 形式传入复杂参数")
    _add_operation_args(p_call)

    # 为每个操作生成便捷子命令
    for name, op in OPERATIONS.items():
        sp = sub.add_parser(name, help=op.description)
        # 每个子命令都支持 --set：与全局参数重名的参数（如 add_monitor 的 url/timeout）
        # 没有便捷 flag，只能通过 --set 传入，因此这条通道必须处处可用。
        sp.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="设置参数（与全局参数重名的参数只能用这种方式传入），可重复使用")
        for prm in op.params:
            # 与全局参数重名的参数不生成 flag（argparse 无法让同一 flag 有两种含义，
            # 强行共存会被全局参数静默吞掉）。它们通过 --set name=value 传入。
            flag = cli_flag_for(op, prm.name)
            if flag is None:
                continue
            help_text = prm.description or ""
            if prm.type:
                help_text = f"[{prm.type}] {help_text}".strip()
            if prm.required_if:
                help_text = (
                    f"{help_text}（当 {prm.required_if} ∈ "
                    f"{', '.join(map(str, prm.required_if_value))} 时必填）"
                ).strip()
            sp.add_argument(flag, dest=f"arg_{prm.name}", required=False, default=None,
                            metavar=prm.name.upper(), help=help_text)
        _add_operation_args(sp)

    return parser


def _add_operation_args(parser: argparse.ArgumentParser) -> None:
    """会真正连接实例的子命令都需要：连接参数 + 输出开关 + 闸门开关。"""
    _add_pure_global_args(parser)
    _add_output_args(parser)
    _add_gate_args(parser)


def _resolve_gate_flags(args) -> None:
    """把挂在两处的开关归一成单一取值，并补齐 SUPPRESS 掉的缺省值。"""
    for attr in ("yes", "dry_run", "as_json", "pretty"):
        setattr(args, attr, bool(getattr(args, attr, None)))
    if getattr(args, "redact", None) is None:
        args.redact = True
    # 连接类参数：从 _conn_* 命名空间搬到约定属性名，缺省自行补齐
    args.url = getattr(args, "_conn_url", None)
    args.username = getattr(args, "_conn_username", None)
    args.password = getattr(args, "_conn_password", None)
    args.token = getattr(args, "_conn_token", "") or ""
    args.timeout = getattr(args, "_conn_timeout", None) or 10
    ssl_verify = getattr(args, "_conn_ssl_verify", None)
    args.ssl_verify = True if ssl_verify is None else ssl_verify
    # CLI 默认**不允许**自动 setup：URL 打错时自动建管理员账号是不可接受的副作用。
    # Python 端也默认关闭，需要时用 --auto-setup 显式开启。
    args.auto_setup = bool(getattr(args, "auto_setup", None))


def _cmd_list(args) -> int:
    if getattr(args, "as_json", False):
        print(json.dumps(describe_all(), ensure_ascii=False,
                         indent=2 if args.pretty else None))
        return 0
    modules = [args.module] if args.module else list(dict.fromkeys(
        op.module for op in OPERATIONS.values()))
    for module in modules:
        ops = list_operations(module)
        if not ops:
            continue
        names = ", ".join(op.name for op in ops)
        print(f"{module} ({len(ops)}):")
        print(f"  {names}")
    print(f"\n共 {len(OPERATIONS)} 个操作。")
    return 0


def _cmd_describe(args) -> int:
    op = OPERATIONS.get(args.operation)
    if op is None:
        print(f"未知操作: {args.operation}", file=sys.stderr)
        return 1
    if getattr(args, "as_json", False):
        print(json.dumps(describe_operation(op.name), ensure_ascii=False,
                         indent=2 if args.pretty else None))
        return 0
    kind = op.effect.value
    print(f"操作: {op.name}")
    print(f"模块: {op.module}    类型: {kind}    返回: {op.returns}")
    print(f"说明: {op.description}")
    print("参数:")
    if not op.params:
        print("  （无）")
    for prm in op.params:
        req = "必填" if prm.required else "可选"
        if prm.required_if:
            req = f"条件必填（{prm.required_if} ∈ {', '.join(map(str, prm.required_if_value))}）"
        enum_info = ""
        if prm.enum is not None:
            enum_info = " 取值: " + ", ".join(str(m.value) for m in prm.enum)
        flag = cli_flag_for(op, prm.name)
        if flag is None:
            flag = f"--set {prm.name}=<…>"
            enum_info += "  （与全局参数重名，只能用 --set 传入）"
        print(f"  {flag}  [{prm.type or 'any'}] ({req}) {prm.description}{enum_info}")
    set_only = [prm.name for prm in op.params if cli_flag_for(op, prm.name) is None]
    if set_only:
        print(f"仅可用 --set 传入的参数: {', '.join(set_only)}")
    print(f"示例:\n  {op.example}")
    return 0


def _suggest_key(operation: str, key: str) -> str:
    known = [prm.name for prm in OPERATIONS[operation].params]
    close = difflib.get_close_matches(key, known, n=3, cutoff=0.5)
    return f"，是否想用: {', '.join(close)}" if close else ""


def _parse_set(items: list[str]) -> dict:
    params: dict = {}
    for item in items:
        if "=" not in item:
            raise ValueError(f"--set 需要 KEY=VALUE 格式: {item}")
        key, value = item.split("=", 1)
        params[key] = value
    return params


def _collect_params(args) -> dict:
    operation = args.operation if args.command == "call" else args.command
    known = {prm.name for prm in OPERATIONS[operation].params}

    if args.command == "call":
        params = _parse_set(args.set)
        if args.params:
            extra = json.loads(args.params)
            if not isinstance(extra, dict):
                raise ValueError("--params 必须是 JSON 对象")
            params.update(extra)
    else:
        # 便捷子命令：先取 flag，再用 --set 覆盖/补充
        # （与全局参数重名的参数只能走 --set）。重复提供同一参数以显式 flag 优先。
        params = {}
        for prm in OPERATIONS[args.command].params:
            value = getattr(args, f"arg_{prm.name}", None)
            if value is not None:
                params[prm.name] = value
        for key, value in _parse_set(args.set).items():
            params.setdefault(key, value)

    # 拼错的键会被静默转发给服务端（edit_monitor 走 data.update(kwargs)），
    # 这里改为直接拒绝，避免"看起来成功、实则写错字段"。
    unknown = [k for k in params if k not in known]
    if unknown:
        raise ValueError(
            f"操作 '{operation}' 不认识参数: {', '.join(unknown)}"
            + "".join(_suggest_key(operation, k) for k in unknown)
        )
    return params


def _check_gate(operation: str, params: dict, args) -> int | None:
    """写操作闸门。返回非 ``None`` 表示应当以此退出码终止。"""
    op = OPERATIONS[operation]
    if op.effect is Effect.FORBIDDEN:
        print(json.dumps({
            "error": f"操作 '{operation}' 被标记为禁止在生产实例上执行",
            "effect": op.effect.value,
            "reason": "该操作不可逆或会触达真实外部渠道，--yes 也无法放行",
        }, ensure_ascii=False), file=sys.stderr)
        return 3
    if op.effect is Effect.WRITE and not args.yes and not args.dry_run:
        print(json.dumps({
            "error": f"操作 '{operation}' 有副作用，需显式 --yes 确认",
            "effect": op.effect.value,
            "hint": "先用 --dry-run 预览将要发送的参数",
        }, ensure_ascii=False), file=sys.stderr)
        return 4
    return None


def main(argv=None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        # argparse 的用法错误统一为契约中的退出码 1（argparse 自身用 2，
        # 而 2 在本工具里表示"服务端/鉴权错误"，必须区分开）。
        return 1 if e.code == 2 else int(e.code or 0)
    _resolve_gate_flags(args)

    if args.command is None:
        parser.print_help()
        return 1
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "describe":
        return _cmd_describe(args)

    operation = args.operation if args.command == "call" else args.command
    if operation not in OPERATIONS:
        print(f"未知操作: {operation}", file=sys.stderr)
        return 1

    try:
        params = coerce_params(operation, _collect_params(args))
    except (ValueError, json.JSONDecodeError) as e:
        message = redact(str(e)) if args.redact else str(e)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 1

    missing = missing_required(operation, params)
    if missing:
        print(json.dumps({
            "error": f"操作 '{operation}' 缺少必填参数: {', '.join(missing)}",
        }, ensure_ascii=False), file=sys.stderr)
        return 1

    gate = _check_gate(operation, params, args)
    if gate is not None:
        return gate

    if args.dry_run:
        shown = normalize_result(params)
        if args.redact:
            shown = redact(shown)
        print(json.dumps({
            "dry_run": True,
            "operation": operation,
            "effect": OPERATIONS[operation].effect.value,
            "params": shown,
            "note": "未连接、未登录、未写入",
        }, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0

    if not args.url:
        print("缺少 --url（实例地址）", file=sys.stderr)
        return 1

    try:
        client = UptimeKumaSkills(
            args.url, args.username, args.password,
            token=args.token, timeout=args.timeout, ssl_verify=args.ssl_verify,
            auto_setup=args.auto_setup,
        )
        try:
            result = client.invoke(operation, **params)
        finally:
            client.close()
    except (UptimeKumaException, Timeout) as e:
        message = redact(str(e)) if args.redact else str(e)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 2
    except (ValueError, TypeError) as e:
        message = redact(str(e)) if args.redact else str(e)
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 1

    normalized = normalize_result(result)
    if args.redact:
        hidden = redacted_fields(normalized)
        normalized = redact(normalized)
    else:
        hidden = []
    print(json.dumps(normalized, ensure_ascii=False,
                     indent=2 if args.pretty else None))
    if hidden:
        print(f"（已遮蔽 {len(hidden)} 个凭据字段；需要原文请加 --no-redact）",
              file=sys.stderr)
    return 0
