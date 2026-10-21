"""操作注册表。

把 ``uptime_kuma_api.UptimeKumaApi`` 的公开方法整理成可按名字调用的「操作」，
并自动从方法签名与 docstring 中提取参数定义、说明与返回值类型。

本模块是操作清单、参数元数据与副作用等级的事实源：CLI 子命令、
``--json`` 自描述和写操作闸门均从这里读取。

三项经实测确立的硬事实（改动本文件前务必先读）：

1. **副作用不能靠名字前缀猜。** ``get_`` / ``test_`` / ``check_`` 前缀与真实副作用不一致：
   ``test_notification`` 会向真实渠道推送真实告警，``test_docker_host`` / ``test_chrome``
   会发起真实外部/服务端动作。因此副作用由 ``Effect`` 显式声明，默认 ``WRITE``（fail-safe）。
2. **通知的必填集不能来自 docstring。** docstring 把各 provider 自己的必填项都标成了必填，
   导致 ``add_notification`` 出现 82 个假必填、而 telegram 真正需要的两个字段反而成了可选。
   改为读取库自身的公开映射 ``notification_provider_options``，算法与库自身校验一致
   （``api.py:353-358``）。
3. **配置字段的可写集合就是 ``add_monitor`` 的参数集**，用于真机漂移比对时区分
   "配置" 与 "派生/运行时" 字段。
"""

import inspect
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from uptime_kuma_api import (
    UptimeKumaApi,
    MonitorType,
    AuthMethod,
    ProxyProtocol,
    DockerType,
    MaintenanceStrategy,
    IncidentStyle,
    NotificationType,
    notification_provider_options,
)

# ---------------------------------------------------------------------------
# 模块 -> 操作（底层方法名）清单
# ---------------------------------------------------------------------------
MODULE_OPERATIONS: dict[str, list[str]] = {
    "auth": [
        "login", "login_by_token", "logout", "need_setup", "setup",
        "change_password", "twofa_status", "prepare_2fa", "verify_token",
        "save_2fa", "disable_2fa",
    ],
    "monitors": [
        "get_monitors", "get_monitor", "add_monitor", "edit_monitor",
        "delete_monitor", "pause_monitor", "resume_monitor", "get_monitor_beats",
        "get_monitor_status", "get_game_list", "test_chrome",
        "add_monitor_tag", "delete_monitor_tag",
    ],
    "status-pages": [
        "get_status_pages", "get_status_page", "add_status_page",
        "delete_status_page", "save_status_page", "post_incident",
        "unpin_incident",
    ],
    "notifications": [
        "get_notifications", "get_notification", "add_notification",
        "edit_notification", "delete_notification", "test_notification",
        "check_apprise",
    ],
    "heartbeats": [
        "get_heartbeats", "get_important_heartbeats", "avg_ping", "uptime",
        "cert_info",
    ],
    "tags": ["get_tags", "get_tag", "add_tag", "edit_tag", "delete_tag"],
    "proxies": [
        "get_proxies", "get_proxy", "add_proxy", "edit_proxy", "delete_proxy",
    ],
    "maintenances": [
        "get_maintenances", "get_maintenance", "add_maintenance",
        "edit_maintenance", "delete_maintenance", "pause_maintenance",
        "resume_maintenance", "get_monitor_maintenance",
        "add_monitor_maintenance", "get_status_page_maintenance",
        "add_status_page_maintenance",
    ],
    "api-keys": [
        "get_api_keys", "get_api_key", "add_api_key", "enable_api_key",
        "disable_api_key", "delete_api_key",
    ],
    "docker-hosts": [
        "get_docker_hosts", "get_docker_host", "add_docker_host",
        "edit_docker_host", "delete_docker_host", "test_docker_host",
    ],
    "system": [
        "version", "info", "get_settings", "set_settings", "get_database_size",
        "shrink_database", "upload_backup", "clear_events", "clear_heartbeats",
        "clear_statistics",
    ],
}

# 参数名 -> 枚举类（字符串入参自动转换为枚举）
ENUM_PARAMS: dict[str, type] = {
    "authMethod": AuthMethod,
    "protocol": ProxyProtocol,
    "dockerType": DockerType,
    "strategy": MaintenanceStrategy,
    "style": IncidentStyle,
}

# 名称为 ``type`` 的参数，其枚举类型随模块不同
TYPE_ENUM_BY_MODULE: dict[str, type] = {
    "monitors": MonitorType,
    "notifications": NotificationType,
}

# 部分使用 ``**kwargs`` 的方法在 docstring 中把必填项标成了 optional，
# 这里补充真实的必填项（最终仍以库自身校验为准）。
REQUIRED_OVERRIDES: dict[str, set[str]] = {
    "add_monitor": {"type", "name"},
    "add_notification": {"name", "type"},
    "test_notification": {"name", "type"},
    "add_proxy": {"protocol", "host", "port"},
    "add_docker_host": {"name", "dockerType"},
    "test_docker_host": {"name", "dockerType"},
    "add_tag": {"name", "color"},
    "add_maintenance": {"title", "strategy"},
}

# 参数名 -> 库中真实 kwarg 名（docstring 与实际签名不一致时的修正）
PARAM_NAME_ALIASES: dict[str, str] = {
    # docstring 写作 timezone，真实 kwarg 是 timezoneOption。
    # 照文档传 timezone 会得到 TypeError: got an unexpected keyword argument 'timezone'。
    "timezone": "timezoneOption",
}

# 库 docstring 明确标为必填、但实现上会被推导/可有默认值的**假必填**参数。
# 例：save_status_page 的 id —— 它的实现是 `get_status_page(slug)` 里推导出来的，
# docstring 却写成必填，逼调用方白传一个参数。
FALSE_REQUIRED: dict[str, set[str]] = {
    "save_status_page": {"id"},
}

# 库 docstring 标为 optional、但实现上**真的需要**的参数（漏标必填）。
# 例：save_status_page 的 title —— `_build_status_page_data(slug, id, title, ...)`
# 要求它存在；docstring 写 optional 会让调用方漏传后拿到服务端错误。
MISSED_REQUIRED: dict[str, set[str]] = {
    "save_status_page": {"title"},
}


# 全局 CLI 参数占用的名字。操作参数与它们重名时**不生成便捷 flag**，
# 改用 `--set <name>=<value>` 传入——因为 argparse 中同一个 flag 字符串不能有两种含义，
# 强行共存会导致全局参数把这个操作参数**静默吞掉**（实测：`add_monitor --url A --url B`
# 中连接地址覆盖了监控地址；`--timeout` 也只作用到连接超时）。
GLOBAL_ARG_NAMES: frozenset[str] = frozenset({
    "url", "username", "password", "token", "timeout", "ssl_verify", "pretty",
    "yes", "dry_run", "json", "no_redact", "redact",
})


def cli_flag_for(op: "Operation", param_name: str) -> Optional[str]:
    """返回某个操作参数在 CLI 上的便捷 flag 名；``None`` 表示只能用 ``--set``。

    与全局参数重名时返回 ``None``：这些参数（如 ``add_monitor`` 的 ``url`` / ``timeout``、
    ``add_proxy`` 的 ``username`` / ``password``、``login`` 的 ``username`` / ``password`` / ``token``）
    必须通过 ``--set url=...`` 传入，避免与连接参数混淆。
    """
    if param_name == "id_":
        return "--id"
    if param_name in GLOBAL_ARG_NAMES:
        return None
    return f"--{param_name}"


def set_only_params(op: "Operation") -> list[str]:
    """只能用 ``--set`` 传入的参数名列表（与全局参数重名者）。"""
    return [prm.name for prm in op.params if cli_flag_for(op, prm.name) is None]


class Effect(str, Enum):
    """操作的副作用等级。

    * ``READ`` —— 无副作用，默认放行。
    * ``WRITE`` —— 有副作用（含向外部渠道推送消息），默认拦截，需 ``--yes``。
    * ``FORBIDDEN`` —— 生产上永不执行，硬性拒绝。

    默认值为 ``WRITE``：未显式声明的操作按"有副作用"对待，这是 fail-safe 方向。
    """

    READ = "read"
    WRITE = "write"
    FORBIDDEN = "forbidden"


# 显式声明为只读的操作（其余一律按 WRITE 处理）
_READ_OPERATIONS: frozenset[str] = frozenset({
    # auth
    "need_setup", "twofa_status",
    # monitors
    "get_monitors", "get_monitor", "get_monitor_beats", "get_monitor_status",
    "get_game_list",
    # status-pages
    "get_status_pages", "get_status_page",
    # notifications
    "get_notifications", "get_notification", "check_apprise",
    # heartbeats
    "get_heartbeats", "get_important_heartbeats", "avg_ping", "uptime",
    "cert_info",
    # tags / proxies / maintenances / api-keys / docker-hosts
    "get_tags", "get_tag",
    "get_proxies", "get_proxy",
    "get_maintenances", "get_maintenance", "get_monitor_maintenance",
    "get_status_page_maintenance",
    "get_api_keys", "get_api_key",
    "get_docker_hosts", "get_docker_host",
    # system
    "version", "info", "get_settings", "get_database_size",
})

# 生产上永不执行：要么毁真实数据，要么触达真实外部渠道。
# 注意 test_* 三个**不是**只读：它们会推送真实告警 / 发起真实外部动作。
_FORBIDDEN_OPERATIONS: frozenset[str] = frozenset({
    # 不可逆地清除真实历史数据
    "clear_heartbeats", "clear_events", "clear_statistics",
    # 会把调用方自己锁在门外 / 掐断自有集成
    "change_password", "enable_api_key", "disable_api_key",
    # 不可逆的整库操作
    "shrink_database", "upload_backup",
    # 全局设置，影响整个实例
    "set_settings",
    # 有真实外部副作用，且在生产上无法免除
    "test_notification", "test_docker_host", "test_chrome",
})

# 真机漂移比对时**必须排除**的字段：派生字段（由其他字段决定，无法独立漂移）
# 与运行时/服务端字段（会被正常活动改动，从而造成假告警）。
DERIVED_OR_RUNTIME_MONITOR_FIELDS: frozenset[str] = frozenset({
    # 派生自 name + 父分组名
    "pathName",
    # 派生自 parent 的精确逆映射；任何无关的新增/移动监控都会扰动它 → 假告警头号来源
    "childrenIDs",
    # 服务端/运行时状态，不能作为配置比对
    "weight", "forceInactive", "maintenance", "dns_last_result",
    "screenshot", "includeSensitiveData",
})

_PARAM_RE = re.compile(r":param\s+([\w.]+?)(,\s*optional)?\s+(\w+):\s*(.*)")
_RTYPE_RE = re.compile(r":rtype:\s*(\S+)")


@dataclass
class Param:
    """一个操作参数的元数据。"""

    name: str
    type: str = ""
    required: bool = False
    description: str = ""
    enum: Optional[Any] = None
    default: object = None
    has_default: bool = False
    # 条件必填：仅当 ``required_if`` 指定的判别参数取到 ``required_if_value`` 之一时才必填。
    # 例：add_notification 的 telegramChatID 仅在 type == telegram 时必填。
    required_if: Optional[str] = None
    required_if_value: tuple = ()


@dataclass
class Operation:
    """一个可调用操作的元数据。"""

    name: str
    module: str
    func: str
    description: str
    params: list[Param] = field(default_factory=list)
    returns: str = "dict"
    effect: Effect = Effect.WRITE
    example: str = ""

    @property
    def side_effect(self) -> bool:
        """兼容旧字段：非只读即视为有副作用。"""
        return self.effect is not Effect.READ


def _type_name(annotation) -> str:
    if annotation is None or annotation is inspect.Parameter.empty:
        return ""
    if isinstance(annotation, type):
        return annotation.__name__
    return str(annotation)


def _summary(doc: str) -> str:
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _parse_doc_params(doc: str) -> tuple[dict[str, Param], list[str]]:
    """解析 docstring 中的 ``:param`` 行，返回 (name -> Param, 出现顺序)。"""
    params: dict[str, Param] = {}
    order: list[str] = []
    for match in _PARAM_RE.finditer(doc):
        type_str, optional, name, desc = (
            match.group(1), match.group(2), match.group(3), match.group(4).strip(),
        )
        params[name] = Param(
            name=name,
            type=type_str,
            required=optional is None,
            description=desc,
        )
        order.append(name)
    return params, order


def _build_provider_required_map() -> dict[str, tuple[str, ...]]:
    """反向映射：provider 专属参数 -> 要求它的 provider 取值列表。

    库的 ``notification_provider_options`` 是 ``{NotificationType: {选项: {"required": bool}}}``。
    注意 ``NotificationType`` 是 **str 值枚举**，键是枚举成员而非裸字符串，直接字符串查找会落空。

    取**并集**：同一参数名可能被多个 provider 使用且要求不同
    （实测 ``title`` 仅对 APPRISE 必填）。因此逐 provider 收集"该 provider 要求它"，
    得到形如 ``{"telegramChatID": ("telegram",), "title": ("apprise",)}``。
    """
    reverse: dict[str, list[str]] = {}
    for provider, options in notification_provider_options.items():
        value = str(getattr(provider, "value", provider))
        for option_name, spec in options.items():
            if spec.get("required"):
                reverse.setdefault(option_name, []).append(value)
    return {name: tuple(providers) for name, providers in reverse.items()}


# provider 专属参数 -> 要求它的 provider 取值（**已转为裸字符串**，
# 因为 NotificationType 是 str 值枚举，直接与 CLI 传入的字符串比较会不相等）
PROVIDER_REQUIRED_MAP: dict[str, tuple[str, ...]] = _build_provider_required_map()

# 上游 _check_arguments_monitor 的按类型必填项中，只有 builder 默认值为 None 的
# 字段需要调用方显式提供。edit_monitor 会先合并已有配置，故仅对新增监控生效。
MONITOR_REQUIRED_BY_TYPE: dict[str, tuple[str, ...]] = {
    "http": ("url",),
    "port": ("hostname", "port"),
    "ping": ("hostname",),
    "keyword": ("url", "keyword"),
    "grpc-keyword": ("grpcUrl", "keyword", "grpcServiceName", "grpcMethod"),
    "dns": ("hostname", "port"),
    "docker": ("docker_host",),
    "steam": ("hostname", "port"),
    "gamedig": ("game", "hostname", "port"),
    "mqtt": ("hostname", "port"),
    "radius": ("radiusUsername", "radiusPassword", "radiusSecret",
               "radiusCalledStationId", "radiusCallingStationId"),
    "json-query": ("url", "jsonPath", "expectedValue"),
    "real-browser": ("url",),
    "kafka-producer": ("kafkaProducerTopic", "kafkaProducerMessage"),
    "tailscale-ping": ("hostname",),
}
MONITOR_REQUIRED_MAP: dict[str, tuple[str, ...]] = {
    name: tuple(monitor_type for monitor_type, fields in MONITOR_REQUIRED_BY_TYPE.items()
                if name in fields)
    for name in {field for fields in MONITOR_REQUIRED_BY_TYPE.values() for field in fields}
}

PARAM_DESCRIPTION_OVERRIDES = {
    "grpcUrl": "gRPC 目标地址",
    "grpcEnableTls": "是否使用 TLS",
    "grpcServiceName": "gRPC 服务名",
    "grpcMethod": "gRPC 方法名",
    "grpcProtobuf": "protobuf 定义",
    "grpcBody": "gRPC 请求体",
    "grpcMetadata": "gRPC 请求元数据",
}


def _required_when_for(operation: str, name: str) -> tuple[Optional[str], tuple]:
    """返回 (判别参数, 触发取值元组)，用于条件必填。"""
    if operation == "add_monitor" and name in MONITOR_REQUIRED_MAP:
        return ("type", MONITOR_REQUIRED_MAP[name])
    if operation in ("add_notification", "test_notification") and name not in ("name", "type"):
        providers = PROVIDER_REQUIRED_MAP.get(name)
        if providers:
            return ("type", providers)
    return (None, ())


def _derive_params(func, module: str, operation: str) -> list[Param]:
    doc = inspect.getdoc(func) or ""
    doc_params, order = _parse_doc_params(doc)

    sig_params: dict[str, inspect.Parameter] = {}
    try:
        for prm in inspect.signature(func).parameters.values():
            if prm.name == "self":
                continue
            if prm.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            sig_params[prm.name] = prm
    except (ValueError, TypeError):
        pass

    enum_for_type = TYPE_ENUM_BY_MODULE.get(module)
    overrides = REQUIRED_OVERRIDES.get(operation, set())
    # 通知类操作：provider 专属参数在 docstring 里被错误地标成必填，
    # 该标记完全不可信（实测 82 个假必填）。这些操作的必填集**只**来自
    # REQUIRED_OVERRIDES（name/type）+ PROVIDER_REQUIRED_MAP（按 type 条件必填）。
    notifications_op = operation in ("add_notification", "edit_notification", "test_notification")

    result: list[Param] = []
    seen: set[str] = set()

    # 优先使用显式签名中的参数（能准确判断必填与默认值）
    for name, prm in sig_params.items():
        doc_prm = doc_params.get(name)
        required = prm.default is inspect.Parameter.empty
        result.append(Param(
            name=name,
            type=(doc_prm.type if doc_prm else _type_name(prm.annotation)),
            required=required or (name in overrides),
            description=(doc_prm.description if doc_prm else ""),
            default=(None if prm.default is inspect.Parameter.empty else prm.default),
            has_default=prm.default is not inspect.Parameter.empty,
        ))
        seen.add(name)

    # 再补充 docstring 中（来自 **kwargs）的参数
    for name in order:
        if name in seen:
            continue
        prm = doc_params[name]
        # provider 专属参数按反向映射精确标记条件必填（优先级最高：
        # 即使 docstring 把它标成了 optional 或 required，都以库的 provider 定义为准）。
        required_if, required_if_value = _required_when_for(operation, name)
        if required_if:
            prm.required = False
            prm.required_if = required_if
            prm.required_if_value = required_if_value
        elif notifications_op:
            # 通知类 kwargs：docstring 的必填标记一律不可信，只认显式 override
            prm.required = name in overrides
        else:
            prm.required = prm.required or (name in overrides)
        result.append(prm)
        seen.add(name)

    # add/edit_monitor 的 docstring 漏掉了 7 个 gRPC 字段。它们是
    # _build_monitor_data 的真实入参；从签名补齐，避免白名单拒绝有效配置。
    if operation in ("add_monitor", "edit_monitor"):
        for name, prm in inspect.signature(UptimeKumaApi._build_monitor_data).parameters.items():
            if name == "self" or name in seen:
                continue
            result.append(Param(
                name=name,
                type=_type_name(prm.annotation),
                required=prm.default is inspect.Parameter.empty,
                default=None if prm.default is inspect.Parameter.empty else prm.default,
                has_default=prm.default is not inspect.Parameter.empty,
            ))
            seen.add(name)

    # 应用参数名修正（docstring 名 -> 库真实 kwarg 名）
    for prm in result:
        alias = PARAM_NAME_ALIASES.get(prm.name)
        if alias:
            prm.name = alias
        if not prm.description and prm.name in PARAM_DESCRIPTION_OVERRIDES:
            prm.description = PARAM_DESCRIPTION_OVERRIDES[prm.name]
        # 条件必填必须在补齐 builder 签名之后标记，才能覆盖 gRPC 字段。
        required_if, required_if_value = _required_when_for(operation, prm.name)
        if required_if:
            prm.required = False
            prm.required_if = required_if
            prm.required_if_value = required_if_value

    # 去掉库 docstring 里的假必填（实现上会被推导或本就有默认值）
    for false_required in FALSE_REQUIRED.get(operation, set()):
        for prm in result:
            if prm.name == false_required:
                prm.required = False
                prm.has_default = True

    # 补上 docstring 漏标的真必填（实现上确实需要，漏传会拿到服务端错误）
    for missed in MISSED_REQUIRED.get(operation, set()):
        for prm in result:
            if prm.name == missed:
                prm.required = True

    # 绑定枚举类型
    for prm in result:
        enum_cls = ENUM_PARAMS.get(prm.name)
        if enum_cls is None and prm.name == "type":
            enum_cls = enum_for_type
        prm.enum = enum_cls

    return result


def _effect_for(name: str) -> Effect:
    if name in _FORBIDDEN_OPERATIONS:
        return Effect.FORBIDDEN
    if name in _READ_OPERATIONS:
        return Effect.READ
    return Effect.WRITE


def _build_example(op: Operation) -> str:
    parts = []
    for prm in op.params:
        if not prm.required:
            continue
        flag = cli_flag_for(op, prm.name)
        if flag is None:
            # 与全局参数重名：只能用 --set 传入
            parts.append(f"--set {prm.name}=<{prm.type or 'value'}>")
        else:
            parts.append(f"{flag} <{prm.type or 'value'}>")
    body = " ".join(parts)
    return (
        f"python -m uptime_kuma_skills --url <URL> --username <USER> --password <PASS> "
        f"{op.name} {body}"
    ).rstrip()


def _build_operations() -> dict[str, Operation]:
    ops: dict[str, Operation] = {}
    for module, names in MODULE_OPERATIONS.items():
        for name in names:
            func = getattr(UptimeKumaApi, name, None)
            if func is None:
                raise RuntimeError(f"uptime_kuma_api 缺少方法: {name}")
            doc = inspect.getdoc(func) or ""
            rtype = _RTYPE_RE.search(doc)
            op = Operation(
                name=name,
                module=module,
                func=name,
                description=_summary(doc),
                params=_derive_params(func, module, name),
                returns=("str" if name == "version" else (rtype.group(1) if rtype else "dict")),
                effect=_effect_for(name),
            )
            ops[name] = op

    for op in ops.values():
        op.example = _build_example(op)
    return ops


OPERATIONS: dict[str, Operation] = _build_operations()


def get_operation(name: str) -> Operation:
    """按名字获取操作，不存在时抛出 ``KeyError``。"""
    try:
        return OPERATIONS[name]
    except KeyError:
        raise KeyError(f"未知操作: {name}")


def list_operations(module: Optional[str] = None) -> list[Operation]:
    """列出全部操作，或指定模块的操作。"""
    ops = list(OPERATIONS.values())
    if module is not None:
        ops = [op for op in ops if op.module == module]
    return ops


def writable_monitor_fields() -> frozenset[str]:
    """监控对象的**可写配置字段**集合。

    取自 ``add_monitor`` 的参数集——实测这就是库 ``_build_monitor_data`` 的定义域，
    即"人类/API 能改的配置"，用于把配置漂移与派生字段变化区分开。
    """
    return frozenset(prm.name for prm in OPERATIONS["add_monitor"].params)


def missing_required(operation: str, params: dict) -> list[str]:
    """返回缺少的必填参数名，已考虑按判别参数生效的条件必填。

    条件必填优先于 ``required``：一个参数若声明了 ``required_if``，
    就只在该条件满足时才要求，不再作为无条件必填（这正是 add_notification
    那 82 个假必填的修法）。
    """
    op = get_operation(operation)
    missing: list[str] = []
    for prm in op.params:
        if prm.name in params and params[prm.name] not in (None, ""):
            continue
        if prm.required_if:
            discriminator = params.get(prm.required_if)
            if discriminator is None:
                continue
            value = str(getattr(discriminator, "value", discriminator))
            if value in prm.required_if_value:
                missing.append(prm.name)
            continue
        if prm.required:
            missing.append(prm.name)
    return missing


def describe_operation(name: str) -> dict:
    """把操作序列化为机器可读结构（``--json`` 自描述）。"""
    op = get_operation(name)
    return {
        "name": op.name,
        "module": op.module,
        "effect": op.effect.value,
        "read_only": op.effect is Effect.READ,
        "description": op.description,
        "returns": op.returns,
        "example": op.example,
        "params": [
            {
                "name": prm.name,
                "type": prm.type or "any",
                "required": prm.required,
                "required_if": prm.required_if,
                "required_if_value": list(prm.required_if_value),
                "enum": ([str(m.value) for m in prm.enum] if prm.enum is not None else None),
                "default": (prm.default if isinstance(prm.default, (str, int, float, bool))
                            or prm.default is None else str(prm.default)),
                "has_default": prm.has_default,
                "description": prm.description,
            }
            for prm in op.params
        ],
    }


def describe_all() -> dict:
    """全部操作的机器可读结构，按模块分组。"""
    modules: list[dict] = []
    for module in dict.fromkeys(op.module for op in OPERATIONS.values()):
        ops = list_operations(module)
        modules.append({
            "module": module,
            "count": len(ops),
            "operations": [describe_operation(op.name) for op in ops],
        })
    return {"total": len(OPERATIONS), "modules": modules}
