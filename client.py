"""统一客户端：自动鉴权与会话管理。

只需传入实例地址、账号、密码三个基础参数，即可自动完成连接与登录，
并对外暴露注册表中的 Uptime Kuma 操作。会话维持、token 复用与断线重连均在内部处理。
"""

import time

from uptime_kuma_api import UptimeKumaApi, UptimeKumaException, Timeout

from .operations import coerce_params, validate_required
from .registry import OPERATIONS, Effect


class UptimeKumaSkills:
    """Uptime Kuma 技能集统一入口。

    :param str url: Uptime Kuma 实例地址，例如 ``https://uptime.example.com/``
    :param str username: 登录账号
    :param str password: 登录密码
    :param str token: 可选。已有登录 token 时可直接复用
    :param float timeout: 连接/响应超时（秒），默认 10
    :param bool ssl_verify: 是否校验 SSL 证书，自签证书实例设为 False
    :param bool auto_setup: 实例未初始化时是否用传入账号密码自动完成初始化。
        默认 **False**：URL 打错或指向一个未初始化的实例时，自动 setup 会**凭空创建一个
        管理员账号**，这是不可接受的副作用，因此改为显式开启。
    """

    def __init__(
        self,
        url: str,
        username: str = None,
        password: str = None,
        token: str = "",
        timeout: float = 10,
        ssl_verify: bool = True,
        auto_setup: bool = False,
    ) -> None:
        self.url = url
        self.username = username
        self.password = password
        self.auto_setup = auto_setup
        self._token = token or ""
        self._api = UptimeKumaApi(url, timeout=timeout, ssl_verify=ssl_verify)
        self._authenticate()

    # ----- 会话管理 -----

    def _authenticate(self) -> None:
        """登录（优先 token，其次账号密码，必要时先初始化）。"""
        api = self._api
        if self._token:
            api.login_by_token(self._token)
            return

        if self.username and self.password:
            if self.auto_setup and api.need_setup():
                api.setup(self.username, self.password)
            result = api.login(self.username, self.password)
            if isinstance(result, dict) and result.get("token"):
                self._token = result["token"]
            return

        # 未提供账号密码：尝试免鉴权自动登录（disableAuth 场景）
        api.login()

    def _reconnect(self) -> None:
        """断开后重连并重新登录。"""
        try:
            self._api.disconnect()
        except Exception:
            pass
        self._api.connect()
        self._authenticate()

    def _ensure_session(self) -> None:
        """确保底层 socket 处于已连接状态。"""
        if not getattr(self._api.sio, "connected", False):
            self._reconnect()

    # ----- 调用入口 -----

    def invoke(self, operation: str, *args, **kwargs):
        """按操作名调用，自动完成参数强转、必填校验、会话维持。

        既支持关键字参数（``invoke("add_monitor", type="http", ...)``），
        也支持位置参数（``invoke("get_monitor", 6)``）。
        """
        op = OPERATIONS.get(operation)
        if op is None:
            raise ValueError(f"未知操作: {operation}")
        coerced = coerce_params(operation, kwargs)
        # 仅在使用关键字参数时才做必填校验（位置参数无法按名映射）
        if not args:
            validate_required(operation, coerced)
        return self._call_method(op.func, args, coerced)

    def _call_method(self, func_name: str, args: tuple, kwargs: dict):
        self._ensure_session()
        attr = getattr(self._api, func_name)
        # 少数操作是属性（如 version），直接返回其值
        if not callable(attr):
            return attr
        reconnected = False
        for attempt in range(3):
            try:
                return attr(*args, **kwargs)
            except (UptimeKumaException, Timeout) as error:
                # 服务端可能已执行写入但响应丢失；写操作绝不自动重放。
                if (not getattr(self._api.sio, "connected", False)
                        and self._is_read_only(func_name) and not reconnected):
                    self._reconnect()
                    attr = getattr(self._api, func_name)
                    reconnected = True
                    continue
                # 上游 get_monitor_status 基于异步心跳快照，冷会话的首个快照
                # 可能不完整。只针对这个已知、只读的误报有限重读。
                stale_status = (func_name == "get_monitor_status"
                                and isinstance(error, UptimeKumaException)
                                and "monitor does not exist" in str(error).lower())
                if stale_status and attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                raise

    @staticmethod
    def _is_read_only(func_name: str) -> bool:
        op = OPERATIONS.get(func_name)
        return op is not None and op.effect is Effect.READ

    def __getattr__(self, name: str):
        # 仅处理未定义的属性；下划线开头交由默认逻辑（避免 __init__ 期间递归）
        if name.startswith("_"):
            raise AttributeError(name)
        if name in OPERATIONS:
            # 属性型操作（如 version）直接返回值
            if isinstance(getattr(UptimeKumaApi, name, None), property):
                return self._call_method(name, (), {})

            def _caller(*args, **kwargs):
                return self.invoke(name, *args, **kwargs)
            _caller.__name__ = name
            _caller.__doc__ = OPERATIONS[name].description
            return _caller
        raise AttributeError(name)

    # ----- 便捷属性 -----

    @property
    def api(self) -> UptimeKumaApi:
        return self._api

    @property
    def token(self) -> str:
        return self._token

    # ----- 生命周期 -----

    def close(self) -> None:
        """退出登录并断开连接。"""
        try:
            self._api.logout()
        except Exception:
            pass
        try:
            self._api.disconnect()
        except Exception:
            pass

    def __enter__(self) -> "UptimeKumaSkills":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
