"""真机自建自毁测试（`--live`）——唯一允许在生产实例上运行的测试形态。

**与 `selftest.py` 的分工**

* ``selftest.py`` —— 离线回归，不联网，覆盖 CLI 行为。随便跑。
* 本模块 —— **会连接真实实例并创建/修改/删除对象**。默认不执行，必须显式 ``--live``。

**安全契约（AGENTS.md §8.5，十条，实现中逐条对应）**

1. 临时对象名一律 ``__dshtest_<runid>_<op>``。
2. 回收只认**精确前缀** ``__dshtest_``；跨进程遗留只识别、只报告，**绝不自动删除**——
   模糊匹配一旦写错就会删掉真实对象（实例上 ``id=20「测试数据库监控服务」`` 就是真实生产）。
3. 绝不触碰既有监控/通知/状态页/API Key：只对**自己创建的**对象做增删改。
4. 新监控必须是"孤岛"：``notificationIDList=[]``、``parent=None``，检查间隔设为一小时，
   随后尽快暂停并在秒级内删除。上游 ``add_monitor`` 不接受 ``active=False`` 参数。
5. ``try/finally`` 强制回收；回收失败会在报告中显式标红。
6. 单进程、一次登录跑完"建→验→删"，规避实例的登录限流
   （一次性 CLI 调用每次都会重新登录，实测会撞 ``Too frequently, try again later .``）。
7. 漂移比对只比对**可写配置字段**，排除派生/运行时字段（``childrenIDs`` 是头号假告警来源，
   因为别人在网页上加个监控就会扰动它）。
8. 不用空列表判定对象是否存在（``get_monitor_beats`` 对"不存在"与"无心跳"都返回 ``[]``）。
9. 不依赖 id 预测（虽然实测 id 不复用、下一个预计是 94），一律按名字定位。
10. 禁用清单不在本模块内调用（``clear_*``/``change_password``/``shrink_database``/
    ``upload_backup``/``set_settings``/``test_*``/``enable_api_key``/``disable_api_key``）。

用法::

    # 只读诊断：列出疑似遗留的测试对象（不创建、不删除）
    python -m uptime_kuma_skills.selftest_live --url <URL> --username <U> --password <P> --check-orphans

    # 真正跑一轮自建自毁
    python -m uptime_kuma_skills.selftest_live --url <URL> --username <U> --password <P> --live
"""

import argparse
import os
import sys
import time
import uuid

from .client import UptimeKumaSkills
from .registry import DERIVED_OR_RUNTIME_MONITOR_FIELDS, writable_monitor_fields

# 只有精确这个前缀才被认为是"我们建的"。绝不做模糊匹配、绝不匹配中文"测试"字样。
TEST_PREFIX = "__dshtest_"

# 服务端在新建监控时自动补的字段：不参与比对（它们随创建方式变化，不是用户意图）
_IGNORED_WHEN_COMPARING = DERIVED_OR_RUNTIME_MONITOR_FIELDS


def _new_run_id() -> str:
    return time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6]


def _struct(m: dict) -> dict:
    """监控对象的"可写配置"规范形式，用于漂移比对。

    只保留可写配置字段，排除派生/运行时字段。按字段名排序输出，
    使 list/dict 的顺序差异不会造成假告警。
    """
    fields = (writable_monitor_fields() - _IGNORED_WHEN_COMPARING) | {"active"}
    return {k: m.get(k) for k in sorted(fields)}


def _monitors(skills: UptimeKumaSkills, attempts: int = 3) -> list[dict]:
    """读取监控列表，并规避"快照不完整"这个坑。

    **新登录后（以及写操作后立刻）的第一次 ``get_monitors`` 可能不完整或滞后**：
    ``_get_event_data`` 在第一个 ``heartbeatList`` 事件到达时即返回（``api.py:533-544``），
    实测冷调用只拿到 1 个监控、同会话第二次才拿到全部 69 个。

    因此这里连续读两次并**取第二次**；若第二次反而更少，则再读一次取最多的一次。
    这也是本测试一开始误报"删除后仍能按名字找到"的原因——不是删除失败，是读取滞后。
    """
    best = skills.get_monitors() or []
    for _ in range(max(1, attempts - 1)):
        current = skills.get_monitors() or []
        if len(current) >= len(best):
            best = current
        if current:
            break
    return best


def _snapshot(skills: UptimeKumaSkills) -> dict:
    """取一份完整快照，键为监控 id，值为规范化后的可写配置。"""
    return {m["id"]: _struct(m) for m in _monitors(skills)}


def _wait_for(skills: UptimeKumaSkills, predicate, tries: int = 6, delay: float = 0.6):
    """轮询直到 ``predicate(monitors)`` 为真；返回 (是否成功, 最后一次的列表)。

    用于"刚建/刚改/刚删"之后的断言：这类变更可能不会立刻反映在下一次读取里。
    """
    monitors = _monitors(skills)
    for _ in range(tries):
        if predicate(monitors):
            return True, monitors
        time.sleep(delay)
        monitors = _monitors(skills)
    return bool(predicate(monitors)), monitors


def _find_by_name(skills: UptimeKumaSkills, name: str) -> dict | None:
    """按**精确名字**查找监控（不使用模糊匹配）。"""
    for m in _monitors(skills):
        if m.get("name") == name:
            return m
    return None


def find_orphans(skills: UptimeKumaSkills) -> list[dict]:
    """列出疑似遗留的测试对象。**只读，不删除。**"""
    return [m for m in _monitors(skills)
            if str(m.get("name", "")).startswith(TEST_PREFIX)]


def run_live(url: str, username: str, password: str, ssl_verify: bool,
             timeout: float = 30.0) -> int:
    """执行一轮自建自毁。返回进程退出码。"""
    run_id = _new_run_id()
    name = f"{TEST_PREFIX}{run_id}_add_monitor"
    created_name = name
    failures: list[str] = []
    notes: list[str] = []

    skills = UptimeKumaSkills(url, username, password,
                              ssl_verify=ssl_verify, timeout=timeout)
    created_id = None
    try:
        print(f"[1/6] 建立基线快照（单次登录，run_id={run_id}）")
        baseline = _snapshot(skills)
        print(f"      基线监控数: {len(baseline)}")

        # ---- 先做只读诊断：报告遗留，但不自动删除 ----
        orphans = find_orphans(skills)
        if orphans:
            notes.append(
                f"发现 {len(orphans)} 个疑似遗留测试对象（**未自动删除**，请人工确认后处理）: "
                + ", ".join(f"id={m['id']} name={m['name']}" for m in orphans)
            )
            for m in orphans:
                print(f"      [遗留] id={m['id']} name={m['name']}")
        else:
            print("      遗留检查: 无")

        # ---- 建：孤岛监控 ----
        #
        # 注意：**不能**传 active=False —— 库的 `_build_monitor_data` 不接受该 kwarg
        # （实测 ``TypeError: got an unexpected keyword argument 'active'``），
        # 它只在 `_build_monitor_data` 内部以默认值出现。
        #
        # 不做检查的实际保障来自两点，都经实测确认：
        #   1) 新监控不带任何通知（notificationIDList 为空）→ 即使 down 也**不会告警**；
        #      实测 add_monitor **不会**自动订阅 isDefault 通知（既有 81/82/83/85/92/93 全为空）。
        #   2) interval=3600 → Uptime Kuma 要等一个完整周期才做首次检查，
        #      而本测试在秒级内就把它删了，因此它**从不产生任何心跳**。
        print(f"[2/6] 创建临时监控 {name!r}（interval=3600, notificationIDList=[]）")
        created = skills.invoke(
            "add_monitor",
            type="http", name=name, url="http://127.0.0.1:1/",
            interval=3600, retryInterval=3600, maxretries=0,
            notificationIDList=[],
        )
        created_id = created.get("monitorID") if isinstance(created, dict) else None
        if created_id is None:
            failures.append(f"创建返回体没有 monitorID: {created!r}")
            return _report(failures, notes)

        # 立刻暂停，进一步确保它不会执行检查（失败只记 NOTE，不阻断）
        try:
            skills.invoke("pause_monitor", created_id)
            print("      已创建并暂停（pause_monitor）")
        except Exception as e:  # noqa: BLE001
            notes.append(f"pause_monitor 未成功（不阻断，interval=3600 已足够安全）: {e}")
            print(f"      已创建 id={created_id}（暂停失败，见 NOTE）")

        fetched = _find_by_name(skills, name)
        if fetched is None:
            # 刚建完可能还没反映到读取结果里，轮询确认
            ok, _ = _wait_for(skills, lambda ms: any(m.get("name") == name for m in ms))
            fetched = _find_by_name(skills, name)
            if not ok or fetched is None:
                failures.append("创建后按名字找不到该监控")
                return _report(failures, notes)

        # 孤岛校验：绝不能带上通知，否则可能触发真实告警
        if fetched.get("notificationIDList"):
            failures.append(
                f"新监控竟带上了通知 {fetched['notificationIDList']} —— 违反孤岛约束")
        else:
            print("      孤岛校验: notificationIDList 为空 ✓")
        if fetched.get("parent") is not None:
            failures.append(f"新监控竟有 parent={fetched['parent']} —— 违反孤岛约束")
        else:
            print("      孤岛校验: parent 为空 ✓")

        # ---- 改：验证 edit 真的落盘（同样可能滞后，需轮询） ----
        print("[3/6] 修改 interval 3600 → 7200 并回读")
        skills.invoke("edit_monitor", id_=created_id, interval=7200)
        edited_ok, _ = _wait_for(
            skills,
            lambda ms: any(m.get("name") == name and m.get("interval") == 7200 for m in ms))
        after_edit = _find_by_name(skills, name)
        if not edited_ok or after_edit is None or after_edit.get("interval") != 7200:
            failures.append(
                "edit 未生效: interval="
                + str(None if after_edit is None else after_edit.get("interval")))
        else:
            print("      interval=7200 ✓")

        # ---- 删 ----
        print("[4/6] 删除临时监控")
        skills.invoke("delete_monitor", created_id)
        gone_ok, _ = _wait_for(
            skills, lambda ms: not any(m.get("name") == name for m in ms))
        if not gone_ok or _find_by_name(skills, name) is not None:
            failures.append("删除后仍能按名字找到该监控")
        else:
            created_id = None  # 已确认删除，finally 无需再删
            print("      已删除 ✓")

        # ---- 验：零漂移 ----
        print("[5/6] 零漂移校验（排除派生字段，新增记为 INFO、删除记为失败）")
        final = _snapshot(skills)

        deleted = set(baseline) - set(final)
        added = set(final) - set(baseline)
        if deleted:
            failures.append(f"有监控消失: {sorted(deleted)}")
        if added:
            # 用户随时可能在网页上新增监控，这是正常活动，不应算失败
            notes.append(f"期间新增了监控（信息，不算失败）: {sorted(added)}")

        changed = []
        for mid in sorted(set(baseline) & set(final)):
            if baseline[mid] != final[mid]:
                diffs = [k for k in baseline[mid]
                         if baseline[mid][k] != final[mid].get(k)]
                changed.append((mid, diffs))
        if changed:
            for mid, diffs in changed:
                failures.append(f"监控 id={mid} 的配置被改动: {diffs}")
        else:
            print(f"      结构字段零漂移 ✓（比对 {len(set(baseline) & set(final))} 个既有监控）")

        # ---- 遗留复查 ----
        print("[6/6] 遗留复查")
        remaining = [m for m in find_orphans(skills)
                     if not (created_id is not None and m["id"] == created_id)]
        if remaining:
            failures.append(
                f"仍有遗留测试对象: {[(m['id'], m['name']) for m in remaining]}")
        else:
            print("      无遗留 ✓")

        return _report(failures, notes, ok_message="自建自毁通过：建→改→删→零漂移→无遗留")
    finally:
        # ---- 强制回收：无论上面怎么失败，都不能把临时对象留在生产上 ----
        if created_id is not None:
            try:
                skills.invoke("delete_monitor", created_id)
                print(f"      [回收] 已在 finally 中删除 id={created_id}")
            except Exception as e:  # noqa: BLE001
                print(f"      [回收失败] id={created_id} 未能删除: {e}",
                      file=sys.stderr)
                print(f"      [需人工处理] 请手动删除 name={created_name!r} (id={created_id})",
                      file=sys.stderr)
        skills.close()


def _report(failures: list[str], notes: list[str], ok_message: str = "") -> int:
    print()
    if ok_message and not failures:
        print(f"结果: PASS — {ok_message}")
    else:
        print(f"结果: FAIL — {len(failures)} 项")
    for f in failures:
        print(f"  FAIL  {f}")
    for n in notes:
        print(f"  NOTE  {n}")
    return 1 if failures else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="selftest_live",
        description="真机自建自毁测试（会创建/删除临时对象；默认不执行，需 --live）",
    )
    ap.add_argument("--url", default=os.environ.get("UK_URL"))
    ap.add_argument("--username", default=os.environ.get("UK_USERNAME"))
    ap.add_argument("--password", default=os.environ.get("UK_PASSWORD"))
    ap.add_argument("--no-ssl-verify", dest="ssl_verify", action="store_false", default=True)
    ap.add_argument("--timeout", type=float, default=30.0)
    ap.add_argument("--live", action="store_true",
                    help="确认执行：会真的创建并删除一个临时监控")
    ap.add_argument("--check-orphans", action="store_true",
                    help="只读诊断：列出疑似遗留的测试对象，不做任何增删")
    args = ap.parse_args(argv)

    if not args.url or not args.username or not args.password:
        print("需要 --url / --username / --password（或 UK_URL / UK_USERNAME / UK_PASSWORD）",
              file=sys.stderr)
        return 1

    if not args.live and not args.check_orphans:
        print("拒绝执行：本测试会在实例上创建对象，必须显式 --live。\n"
              "只读诊断请用 --check-orphans。", file=sys.stderr)
        return 1

    if args.check_orphans:
        skills = UptimeKumaSkills(args.url, args.username, args.password,
                                  ssl_verify=args.ssl_verify, timeout=args.timeout)
        try:
            orphans = find_orphans(skills)
            if not orphans:
                print("无遗留测试对象。")
                return 0
            print(f"发现 {len(orphans)} 个疑似遗留对象（**不会自动删除**，请人工确认）:")
            for m in orphans:
                print(f"  id={m['id']}  type={m.get('type')}  name={m['name']!r}  "
                      f"notifications={m.get('notificationIDList')}")
                wf = writable_monitor_fields()
                print(f"     创建时的关键字段: "
                      + ", ".join(f"{k}={m.get(k)!r}" for k in ("url", "interval", "active")
                                  if k in wf or k == "active"))
            return 0
        finally:
            skills.close()
    return run_live(args.url, args.username, args.password, args.ssl_verify, args.timeout)


if __name__ == "__main__":
    sys.exit(main())
