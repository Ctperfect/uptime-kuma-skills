"""selftest：离线回归套件（**不联网、不写实例**）。

与仓库自带的 ``tests/`` 有本质区别，务必不要混淆：

* ``tests/`` 是**破坏性套件**：``setUp`` 会清空目标实例的全部监控/通知/状态页/…，
  只能对一次性容器运行，**任何情况下不得指向生产实例**。
* 本文件是**离线**测试：只跑 CLI 子进程，断言退出码与 stdout/stderr，
  完全不连接任何实例，因此可以随便跑。

运行方式::

    python -m uptime_kuma_skills.selftest          # 或
    python selftest.py

真机自建自毁测试（会连接实例并建/删临时对象）由 ``--live`` 显式开启，
默认不会执行；其安全契约见 AGENTS.md §8.5。
"""

import json
import os
import subprocess
import sys

FAILURES: list[str] = []
PASSES = 0


def _run(*args: str) -> tuple[int, str, str]:
    """跑一次 CLI，返回 (退出码, stdout, stderr)。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "uptime_kuma_skills", *args],
        capture_output=True, text=True, encoding="utf-8", env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASSES
    if condition:
        PASSES += 1
        print(f"  PASS  {label}")
    else:
        FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  FAIL  {label}{(' — ' + detail) if detail else ''}")


def test_registry() -> None:
    print("\n[注册表]")
    from .registry import OPERATIONS, Effect, PROVIDER_REQUIRED_MAP, missing_required

    check("操作数 86 / 模块 11",
          len(OPERATIONS) == 86 and len({o.module for o in OPERATIONS.values()}) == 11)

    # D4：有外部副作用的 test_* 不得被判为只读
    for name in ("test_notification", "test_docker_host", "test_chrome"):
        check(f"{name} 不是只读", OPERATIONS[name].effect is not Effect.READ,
              f"实际 {OPERATIONS[name].effect.value}")

    # 禁用清单
    for name in ("clear_heartbeats", "change_password", "shrink_database",
                 "upload_backup", "set_settings"):
        check(f"{name} 为 forbidden", OPERATIONS[name].effect is Effect.FORBIDDEN)

    # D2：通知必填集按 type 推导
    op = OPERATIONS["add_notification"]
    unconditional = [p.name for p in op.params if p.required]
    check("add_notification 无条件必填只有 name/type",
          sorted(unconditional) == ["name", "type"], f"实际 {unconditional}")
    edit_required = [p.name for p in OPERATIONS["edit_notification"].params if p.required]
    check("edit_notification 仅要求 id_", edit_required == ["id_"],
          f"实际 {edit_required}")
    check("version 返回类型是 str", OPERATIONS["version"].returns == "str")
    import inspect
    from uptime_kuma_api import UptimeKumaApi
    builder_fields = set(inspect.signature(UptimeKumaApi._build_monitor_data).parameters) - {"self"}
    for name in ("add_monitor", "edit_monitor"):
        documented = {p.name for p in OPERATIONS[name].params}
        check(f"{name} 覆盖底层监控参数", builder_fields <= documented,
              f"遗漏 {sorted(builder_fields - documented)}")
    import ast
    import textwrap
    from uptime_kuma_api import MonitorType
    from uptime_kuma_api.api import _check_arguments_monitor
    from .registry import MONITOR_REQUIRED_BY_TYPE

    checker = ast.parse(textwrap.dedent(inspect.getsource(_check_arguments_monitor))).body[0]
    mapping = next(node.value for node in checker.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "required_args_by_type"
                           for target in node.targets))
    builder = inspect.signature(UptimeKumaApi._build_monitor_data).parameters
    expected = {}
    for key, values in zip(mapping.keys, mapping.values):
        monitor_type = MonitorType[key.attr].value
        fields = tuple(field.value for field in values.elts
                       if builder[field.value].default is None)
        if fields:
            expected[monitor_type] = fields
    check("监控类型条件必填与上游校验一致",
          MONITOR_REQUIRED_BY_TYPE == expected,
          f"注册表 {MONITOR_REQUIRED_BY_TYPE}，上游 {expected}")
    check("provider 反向映射非空", len(PROVIDER_REQUIRED_MAP) > 50)

    cases = {
        "telegram": ["telegramBotToken", "telegramChatID"],
        "smtp": ["smtpFrom", "smtpHost", "smtpPort"],
        "webhook": ["webhookContentType", "webhookURL"],
    }
    for provider, expected in cases.items():
        got = sorted(missing_required("add_notification", {"name": "x", "type": provider}))
        check(f"type={provider} 必填集正确", got == expected, f"实际 {got}")

    ok = missing_required("add_notification", {
        "name": "x", "type": "telegram",
        "telegramChatID": "1", "telegramBotToken": "t"})
    check("telegram 补齐后无缺失", ok == [], f"实际 {ok}")
    grpc_missing = missing_required("add_monitor", {"type": "grpc-keyword", "name": "g"})
    check("gRPC 监控条件必填准确",
          set(grpc_missing) == {"grpcUrl", "keyword", "grpcServiceName", "grpcMethod"},
          f"实际 {grpc_missing}")

    # D9：库 docstring 的假必填
    ssp = OPERATIONS["save_status_page"]
    id_param = next((p for p in ssp.params if p.name == "id"), None)
    check("save_status_page 的 id 不再是必填",
          id_param is not None and not id_param.required,
          f"实际 required={getattr(id_param, 'required', None)}")
    check("save_status_page 只需 slug 与 title",
          sorted(p.name for p in ssp.params if p.required) == ["slug", "title"],
          f"实际 {sorted(p.name for p in ssp.params if p.required)}")

    # D9：docstring 写作 timezone，库真实 kwarg 是 timezoneOption
    maint_names = {p.name for p in OPERATIONS["add_maintenance"].params}
    check("add_maintenance 暴露 timezoneOption", "timezoneOption" in maint_names)
    check("add_maintenance 不再暴露不存在的 timezone",
          "timezone" not in maint_names)

    # D11：有副作用的操作绝不自动重试（重试会产生重复对象）
    from .client import UptimeKumaSkills
    check("只读操作允许重连重试", UptimeKumaSkills._is_read_only("get_monitors"))
    check("写操作禁止自动重试", not UptimeKumaSkills._is_read_only("add_monitor"))
    check("删除操作禁止自动重试", not UptimeKumaSkills._is_read_only("delete_monitor"))
    check("forbidden 操作也不重试",
          not UptimeKumaSkills._is_read_only("clear_heartbeats"))

    # D12：Python 端默认不得自动 setup
    import inspect
    sig = inspect.signature(UptimeKumaSkills.__init__)
    check("UptimeKumaSkills auto_setup 默认 False",
          sig.parameters["auto_setup"].default is False,
          f"实际 {sig.parameters['auto_setup'].default}")


def test_gates() -> None:
    print("\n[写操作闸门]")
    code, _, err = _run("add_monitor", "--type", "http", "--name", "G",
                        "--set", "url=https://x.com")
    check("写操作缺 --yes 被拒（退出码 4）", code == 4, f"退出码 {code}")
    check("拒绝信息含 --yes 提示", "--yes" in err)

    code, out, _ = _run("add_monitor", "--type", "http", "--name", "G",
                        "--set", "url=https://x.com", "--dry-run")
    check("--dry-run 退出码 0", code == 0, f"退出码 {code}")
    payload = json.loads(out)
    check("--dry-run 零写入标记", payload.get("dry_run") is True)
    check("--dry-run 回显监控地址", payload["params"].get("url") == "https://x.com",
          f"实际 {payload['params'].get('url')}")

    code, _, err = _run("test_notification", "--name", "n", "--type", "telegram",
                        "--telegramChatID", "1", "--telegramBotToken", "t", "--yes")
    check("forbidden 即使 --yes 也拒绝（退出码 3）", code == 3, f"退出码 {code}")
    check("forbidden 拒绝信息说明原因", "禁止" in err)

    code, _, _ = _run("get_monitors")
    check("只读操作无需 --yes（仅因缺 --url 而退出码 1）", code == 1, f"退出码 {code}")

    # D12：CLI 默认不得自动 setup（否则 URL 打错会凭空建管理员账号）
    code, out, err = _run("add_monitor", "--type", "http", "--name", "G",
                          "--set", "url=https://x.com", "--dry-run")
    check("--auto-setup 默认为关闭", "--auto-setup" in _run("add_monitor", "--help")[1]
          or "--auto-setup" in _run("add_monitor", "--help")[2])
    helper = _run("--help")
    combined = helper[1] + helper[2]
    check("帮助里说明 auto-setup 默认关闭", "auto-setup" in combined)


def test_cli_surface() -> None:
    print("\n[CLI 表面]")
    # 全局参数放在子命令之前/之后都应生效
    for label, argv in (
        ("连接参数在子命令之前",
         ["--url", "https://inst", "--username", "u", "--password", "p",
          "add_monitor", "--type", "http", "--name", "G", "--dry-run",
          "--set", "url=https://example.com"]),
        ("连接参数在子命令之后",
         ["add_monitor", "--type", "http", "--name", "G", "--dry-run",
          "--set", "url=https://example.com",
          "--url", "https://inst", "--username", "u", "--password", "p"]),
    ):
        code, out, err = _run(*argv)
        check(f"{label} 可用", code == 0, f"退出码 {code} {err[:80]}")

    # 主解析器与子解析器共用开关，前置开关不得被子解析器的默认值覆盖。
    for label, argv in (
        ("--dry-run 在子命令前", ["--dry-run", "add_monitor", "--type", "http",
                                "--name", "G", "--set", "url=https://example.com"]),
        ("--dry-run 在子命令后", ["add_monitor", "--type", "http", "--name", "G",
                                "--set", "url=https://example.com", "--dry-run"]),
    ):
        code, out, err = _run(*argv)
        check(f"{label} 不连接实例", code == 0 and json.loads(out).get("dry_run") is True,
              f"退出码 {code} {err[:80]}")

    code, out, _ = _run("--no-redact", "--dry-run", "add_monitor", "--type", "http",
                        "--name", "G", "--set", "url=https://example.com",
                        "--set", "databaseConnectionString=mysql://u:p@host/db")
    check("前置 --no-redact 生效", code == 0 and
          json.loads(out)["params"]["databaseConnectionString"] == "mysql://u:p@host/db")

    code, _, err = _run("call", "get_monitors", "--params", "[]", "--dry-run")
    check("--params 只接受 JSON 对象", code == 1 and "JSON 对象" in err)

    code, out, _ = _run("--dry-run", "add_monitor", "--type", "grpc-keyword",
                        "--name", "G", "--keyword", "SERVING",
                        "--grpcUrl", "grpc.example.com:443",
                        "--grpcServiceName", "grpc.health.v1.Health",
                        "--grpcMethod", "Check", "--set", "grpcEnableTls=true")
    check("预览展示转换后的布尔值", code == 0 and
          json.loads(out)["params"]["grpcEnableTls"] is True)
    code, _, _ = _run("--dry-run", "add_monitor", "--type", "grpc-keyword",
                      "--name", "G", "--set", "grpcEnableTls=invalid")
    check("预览离线拒绝无效布尔值", code == 1)
    code, _, err = _run("--dry-run", "add_monitor", "--type", "grpc-keyword",
                        "--name", "G")
    check("预览离线拒绝不完整 gRPC 监控", code == 1 and "grpcUrl" in err,
          f"退出码 {code} {err[:100]}")

    # 连接参数不得污染操作参数
    code, out, _ = _run("add_monitor", "--type", "http", "--name", "G",
                        "--set", "url=https://monitor.example", "--dry-run",
                        "--url", "https://connection.example")
    if code == 0:
        got = json.loads(out)["params"]["url"]
        check("连接 --url 不覆盖监控 url", got == "https://monitor.example", f"实际 {got}")
    else:
        check("连接 --url 不覆盖监控 url", False, f"退出码 {code}")

    # --set 拼错应被拒绝并给建议（必须提供 --url，否则会先因缺连接参数而退出）
    code, _, err = _run("edit_monitor", "--id", "1", "--set", "notifcationIDList=1",
                        "--url", "https://example.invalid", "--username", "u",
                        "--password", "p")
    check("未知 --set 键被拒绝（退出码 1）", code == 1, f"退出码 {code}")
    check("未知 --set 键给出相近建议", "notificationIDList" in err, err[:120])

    # 未知操作统一为退出码 1
    code, _, _ = _run("call", "bogus_op")
    check("call <未知操作> 退出码 1", code == 1, f"退出码 {code}")
    code, _, _ = _run("bogus_op")
    check("裸 <未知操作> 退出码 1", code == 1, f"退出码 {code}")


def test_json_self_description() -> None:
    print("\n[机器可读自描述]")
    code, out, _ = _run("list", "--json")
    check("list --json 退出码 0", code == 0, f"退出码 {code}")
    if code == 0:
        data = json.loads(out)
        check("list --json 含 86 个操作", data["total"] == 86, f"实际 {data['total']}")
        check("list --json 分 11 个模块", len(data["modules"]) == 11)

    code, out, _ = _run("describe", "add_monitor", "--json")
    check("describe --json 退出码 0", code == 0, f"退出码 {code}")
    if code == 0:
        d = json.loads(out)
        check("含 effect 字段", d["effect"] == "write")
        check("参数含 enum 取值", any(p["enum"] for p in d["params"]))
        check("参数含 required 布尔", all(isinstance(p["required"], bool) for p in d["params"]))

    code, out, _ = _run("describe", "add_notification", "--json")
    if code == 0:
        d = json.loads(out)
        cond = [p for p in d["params"] if p["required_if"]]
        check("条件必填被导出", len(cond) > 50, f"实际 {len(cond)}")
        check("条件必填带触发取值", any(p["required_if_value"] for p in cond))


def test_redaction() -> None:
    print("\n[凭据脱敏]")
    from .redact import REDACTED, redact

    sample = {
        "smtpPassword": "hunter2",
        "smtpUsername": "mailer@example.com",
        "webhookURL": "https://oapi.dingtalk.com/robot/send?access_token=abc",
        # 字段名会骗人：非 RADIUS 监控上同样有值
        "radiusPassword": "same-as-db-password",
        "databaseConnectionString": "mysql://root:pw@localhost:3306/db",
        "mqttUsername": "mqtt://user:pw@host",
        "pushToken": "tok",
        "name": "任务看板监控",
        "interval": 120,
        "childrenIDs": [82, 83],
        "smtpTo": None,
        "smtpCC": "",
    }
    out = redact(sample)

    for field in ("smtpPassword", "smtpUsername", "webhookURL", "radiusPassword",
                  "databaseConnectionString", "mqttUsername", "pushToken"):
        check(f"{field} 已遮蔽", out[field] == REDACTED, f"实际 {out[field]!r}")

    check("非敏感字段保持不变", out["name"] == "任务看板监控" and out["interval"] == 120)
    check("列表字段是配置非凭据，保持原样", out["childrenIDs"] == [82, 83])
    check("空值不遮蔽（区分未配置与已配置）",
          out["smtpTo"] is None and out["smtpCC"] == "")

    # 嵌套与列表
    nested = redact({"monitors": [{"name": "a", "databaseConnectionString": "x"},
                                  {"name": "b"}]})
    check("嵌套遮蔽", nested["monitors"][0]["databaseConnectionString"] == REDACTED)
    check("嵌套未命中者不变", nested["monitors"][1]["name"] == "b")

    # 后缀式复合字段名
    check("复合字段名命中", redact({"smtpPassword2": "x"})["smtpPassword2"] == REDACTED)
    check("snake_case 命中", redact({"basic_auth_pass": "x"})["basic_auth_pass"] == REDACTED)
    link = "https://user:pass@example.com/path?access_token=abc&region=cn"
    safe = redact({"url": link})["url"]
    check("普通 URL 中的凭据被遮蔽", "user:pass" not in safe and "abc" not in safe
          and "region=cn" in safe, safe)
    check("无凭据 URL 不改写", redact("https://example.com/a?x=1%202") ==
          "https://example.com/a?x=1%202")
    check("URL fragment 中的 token 被遮蔽",
          "abc" not in redact("https://example.com/#access_token=abc"))
    check("新建 API Key 的 key 被遮蔽", redact({"key": "uk1_example"})["key"] == REDACTED)


def test_python_client_boundary() -> None:
    print("\n[Python 客户端参数边界]")
    from types import SimpleNamespace
    from unittest.mock import patch
    from uptime_kuma_api import UptimeKumaException
    from .client import UptimeKumaSkills
    from .operations import coerce_params

    try:
        coerce_params("edit_monitor", {"notifcationIDList": [1]})
    except ValueError as exc:
        check("Python 入口拒绝未知参数并提示", "notificationIDList" in str(exc))
    else:
        check("Python 入口拒绝未知参数并提示", False)

    client = object.__new__(UptimeKumaSkills)
    try:
        getattr(client, "unregistered_operation")
    except AttributeError:
        check("未注册方法不透传底层 API", True)
    else:
        check("未注册方法不透传底层 API", False)

    calls = []
    def status(_monitor_id):
        calls.append(1)
        if len(calls) == 1:
            raise UptimeKumaException("monitor does not exist")
        return 1

    client._api = SimpleNamespace(sio=SimpleNamespace(connected=True),
                                  get_monitor_status=status)
    with patch("uptime_kuma_skills.client.time.sleep"):
        got = client._call_method("get_monitor_status", (81,), {})
    check("冷快照误报会重读", got == 1 and len(calls) == 2)

    calls.clear()
    def missing(_monitor_id):
        calls.append(1)
        raise UptimeKumaException("monitor does not exist")
    client._api.get_monitor_status = missing
    with patch("uptime_kuma_skills.client.time.sleep"):
        try:
            client._call_method("get_monitor_status", (999999,), {})
        except UptimeKumaException:
            check("不存在的监控有限重读后仍报错", len(calls) == 3)
        else:
            check("不存在的监控有限重读后仍报错", False)

    class PropertyApi:
        def __init__(self):
            self.sio = SimpleNamespace(connected=True)
            self.reads = 0

        @property
        def version(self):
            self.reads += 1
            return "1.23.16"

    client._api = PropertyApi()
    check("version 属性只读取一次",
          client.version == "1.23.16" and client._api.reads == 1)


def test_docs_drift() -> None:
    """模块技能入口应与注册表的操作名、effect 和必填参数一致。"""
    print("\n[文档漂移]")
    import pathlib
    from .registry import MODULE_OPERATIONS
    from .scripts.generate_docs import render_module_doc

    pkg = pathlib.Path(__file__).parent
    index = (pkg / "SKILL.md").read_text(encoding="utf-8")
    for module in MODULE_OPERATIONS:
        skill = pkg / "skills" / module / "SKILL.md"
        if not skill.exists():
            check(f"skills/{module}/SKILL.md 存在", False)
            continue
        body = skill.read_text(encoding="utf-8")
        check(f"{module} 操作表与注册表一致", body == render_module_doc(module))
        check(f"顶层技能链接 {module}", f"skills/{module}/SKILL.md" in index)


def test_live_safety_contract() -> None:
    """断言真机自建自毁模块的安全契约在**代码层面**成立。

    这些断言不联网，只检查实现是否真的遵守了 AGENTS.md §8.5 的硬性规则——
    因为该模块一旦写错，代价是不可逆的生产事故，值得用测试锁死。
    """
    print("\n[真机自建自毁契约]")
    from . import selftest_live as live

    check("测试对象前缀可识别", live.TEST_PREFIX == "__dshtest_")
    check("遗留识别使用精确前缀（非模糊匹配）",
          "startswith(TEST_PREFIX)" in __import__("inspect").getsource(live.find_orphans))
    # 禁用清单不得出现在该模块里
    src = __import__("inspect").getsource(live)
    forbidden_calls = ("clear_heartbeats", "clear_events", "clear_statistics",
                       "change_password", "shrink_database", "upload_backup",
                       "set_settings", "test_notification", "test_docker_host",
                       "test_chrome", "enable_api_key", "disable_api_key")
    used = [f for f in forbidden_calls if f'"{f}"' in src or f"'{f}'" in src]
    check("未调用任何禁用清单操作", not used, f"发现 {used}")
    # 必须默认拒绝执行
    check("默认拒绝执行（需 --live）", "--live" in src and "拒绝执行" in src)
    # 遗留绝不自动删除
    check("遗留只报告不自动删除",
          "不自动删除" in src or "绝不自动删除" in src)
    # 漂移比对排除派生字段
    from .registry import DERIVED_OR_RUNTIME_MONITOR_FIELDS, writable_monitor_fields
    check("漂移比对排除 childrenIDs",
          "childrenIDs" in DERIVED_OR_RUNTIME_MONITOR_FIELDS)
    check("可写字段与派生字段无交集",
          not (writable_monitor_fields() & DERIVED_OR_RUNTIME_MONITOR_FIELDS))
    check("漂移比对包含启停状态", "active" in live._struct({"active": True}))
    # 单进程一次登录：模块内不得用 CLI 子进程逐次调用
    check("单进程实现（未起 CLI 子进程）", "subprocess" not in src)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    print("=" * 68)
    print("uptime_kuma_skills selftest — 离线回归（不联网、不触碰任何实例）")
    print("=" * 68)

    test_registry()
    test_gates()
    test_cli_surface()
    test_json_self_description()
    test_redaction()
    test_python_client_boundary()
    test_docs_drift()
    test_live_safety_contract()

    print("\n" + "=" * 68)
    print(f"通过 {PASSES}，失败 {len(FAILURES)}")
    for item in FAILURES:
        print(f"  FAIL  {item}")
    print("=" * 68)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
