"""参数强转、校验与结果序列化。

CLI 传入的参数均为字符串，这里依据注册表元数据把它们转成正确类型
（枚举、整数、布尔、JSON 结构），并在调用前做必填校验。
"""

import enum
import difflib
import json

from .registry import get_operation

_TRUE_VALUES = {"true", "1", "yes", "y", "on", "t"}
_FALSE_VALUES = {"false", "0", "no", "n", "off", "f"}


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    raise ValueError(f"无法将 {value!r} 解析为布尔值")


def _to_enum(enum_cls: type, value):
    if isinstance(value, enum_cls):
        return value
    # 1) 直接按枚举值匹配
    try:
        return enum_cls(value)
    except ValueError:
        pass
    # 2) 按枚举名匹配（不区分大小写）
    for member in enum_cls:
        if member.name.lower() == str(value).lower():
            return member
    # 3) 按枚举值匹配（不区分大小写）
    for member in enum_cls:
        if str(member.value).lower() == str(value).lower():
            return member
    valid = ", ".join(str(m.value) for m in enum_cls)
    raise ValueError(f"{value!r} 不是 {enum_cls.__name__} 的合法取值，可选: {valid}")


def _coerce_value(param, value):
    if value is None:
        return None
    if param.enum is not None:
        return _to_enum(param.enum, value)

    type_name = (param.type or "").lower()
    if "bool" in type_name:
        return _to_bool(value)
    if "float" in type_name:
        return float(value)
    if "int" in type_name:
        return int(value)
    if "list" in type_name or "dict" in type_name:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("[") or text.startswith("{"):
                return json.loads(value)
        return value
    return value


def coerce_params(operation: str, params: dict) -> dict:
    """按注册表元数据转换参数值；拒绝未知参数以免静默误配。"""
    op = get_operation(operation)
    meta = {prm.name: prm for prm in op.params}
    unknown = [key for key in params if key not in meta]
    if unknown:
        suggestions = {
            key: difflib.get_close_matches(key, meta, n=3, cutoff=0.5)
            for key in unknown
        }
        hint = "; ".join(
            f"{key} → {', '.join(matches)}" for key, matches in suggestions.items() if matches
        )
        raise ValueError(
            f"操作 '{operation}' 不认识参数: {', '.join(unknown)}"
            + (f"；是否想用: {hint}" if hint else "")
        )
    coerced = {}
    for key, value in params.items():
        coerced[key] = _coerce_value(meta[key], value)
    return coerced


def validate_required(operation: str, params: dict) -> None:
    """校验必填参数（仅做前置提示，最终以库自身校验为准）。

    必填判定包含**条件必填**：例如 ``add_notification`` 的 ``telegramChatID``
    只在 ``type=telegram`` 时才必填，而不是无条件必填（旧版把它连同另外 80 个
    provider 专属字段一起标成必填，导致 add_notification 完全不可用）。
    """
    from .registry import missing_required

    missing = missing_required(operation, params)
    if missing:
        raise ValueError(
            f"操作 '{operation}' 缺少必填参数: {', '.join(missing)}"
        )


def normalize_result(obj):
    """把返回值中的枚举等对象转换为可 JSON 序列化的形式。"""
    if isinstance(obj, enum.Enum):
        value = obj.value
        if isinstance(value, (str, int, float, bool)):
            return value
        return obj.name
    if isinstance(obj, dict):
        return {
            (k.value if isinstance(k, enum.Enum) else k): normalize_result(v)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple, set)):
        return [normalize_result(v) for v in obj]
    return obj
