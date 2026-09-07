# -*- coding: utf-8 -*-
"""T9 Agent Link 事件总线 — 独立验收脚本。

沿用 tools/ 风格：直接 ``python tools/test_agent_link.py`` 运行，退出码 0 即通过。
不依赖 pytest / PySide6。

覆盖范围（与 docs/AgentLink需求.md §6 对齐）：
1. 6 态归一：直接 state + 事件名
2. 未知事件 / 坏 JSON / 超长行 / 缺字段 全部优雅跳过
3. 字节 offset 在重复读取间稳定
4. TTL/超时回退 idle
5. 文件被删 / 重新创建 → 状态被正确回收
6. 多文件多 agent 聚合优先级（error 压过 working）
7. start/stop 幂等
"""
import sys
import tempfile
import threading
import time
from pathlib import Path

# 把项目根加进 path，方便 import agent_link
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent_link import (  # noqa: E402
    AgentLink, MAX_LINE_BYTES, STATES, _EVENT_TO_STATE, normalize_event,
)

PASS = "[PASS]"
FAIL = "[FAIL]"


def check(cond, label):
    print(f"  {PASS if cond else FAIL} {label}")
    return 0 if cond else 1


def section(name):
    print(f"\n=== {name} ===")


def test_normalize_event():
    section("normalize_event: 6 态归一")
    n = 0
    # 直接 state
    n += check(normalize_event({"state": "thinking"}) == "thinking", "直接 state=thinking")
    n += check(normalize_event({"state": "error"}) == "error", "直接 state=error")
    n += check(normalize_event({"state": "BOGUS"}) is None, "未知 state → None")
    # 事件名归一
    n += check(normalize_event({"event": "tool_start"}) == "working", "tool_start → working")
    n += check(normalize_event({"event": "permission"}) == "attention", "permission → attention")
    n += check(normalize_event({"event": "crash"}) == "error", "crash → error")
    n += check(normalize_event({"event": "process_end"}) == "sleeping", "process_end → sleeping")
    n += check(normalize_event({"event": "nonsense"}) is None, "未知 event → None")
    # 非 dict
    n += check(normalize_event("just a string") is None, "非 dict → None")
    n += check(normalize_event(None) is None, "None → None")
    n += check(normalize_event(42) is None, "int → None")
    # state 优先于 event
    n += check(normalize_event({"state": "error", "event": "tool_start"}) == "error",
               "state 字段优先于 event")
    # 空 dict
    n += check(normalize_event({}) is None, "空 dict → None")
    # 所有 6 态都覆盖
    for s in STATES:
        n += check(normalize_event({"state": s}) == s, f"直接 state={s} 归一正确")
    return n


def test_offset_and_bad_inputs():
    section("byte-offset + 坏输入边界")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        link = AgentLink(cfg, poll_sec=0.05, stale_sec=10.0)
        link.start()
        try:
            time.sleep(0.15)  # 让首次扫描跑完
            f = cfg / "agent-events" / "test.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            # 1) 写入正常事件
            with open(f, "ab") as out:
                out.write(b'{"state": "thinking"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "thinking", "thinking 事件被读取")
            # 2) offset 稳定：再写一行不会被吞
            with open(f, "ab") as out:
                out.write(b'{"event": "tool_start"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "working", "追加 writing 事件被读取")
            # 3) 坏 JSON 跳过
            with open(f, "ab") as out:
                out.write(b"this is not json\n")
                out.write(b'{"state": "error"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "error", "坏 JSON 被跳过，下一行 error 生效")
            # 4) 超长行跳过
            big = b'{"state":"thinking","pad":"' + b"x" * (MAX_LINE_BYTES + 100) + b'"}\n'
            with open(f, "ab") as out:
                out.write(big)
                out.write(b'{"state": "working"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "working", "超长行被跳过，下一行 working 生效")
            # 5) 缺字段 / 未知字段
            with open(f, "ab") as out:
                out.write(b'{"foo": "bar"}\n')           # 无 state 无 event
                out.write(b'{"state": 42}\n')              # state 类型错
                out.write(b'{"state": null}\n')            # state 是 null
            time.sleep(0.2)
            # state 没变仍是 working（最后正常行是 working）
            n += check(link.get_state() == "working", "缺字段/类型错全部跳过，不影响已有态")
        finally:
            link.stop()
    return n


def test_stale_ttl():
    section("TTL 超时回退 idle")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        # stale=0.3s, poll=0.05s
        link = AgentLink(cfg, poll_sec=0.05, stale_sec=0.3)
        link.start()
        try:
            time.sleep(0.15)
            f = cfg / "agent-events" / "x.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "ab") as out:
                out.write(b'{"state": "error"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "error", "刚写入 → error")
            # 等过期
            time.sleep(0.6)
            n += check(link.get_state() == "idle", "过期 → 自动回退 idle")
        finally:
            link.stop()
    return n


def test_multi_agent_aggregation():
    section("多 agent 聚合优先级")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        link = AgentLink(cfg, poll_sec=0.05, stale_sec=10.0)
        link.start()
        try:
            time.sleep(0.15)
            evdir = cfg / "agent-events"
            evdir.mkdir(parents=True, exist_ok=True)
            # 3 个 agent 同时存在
            (evdir / "claude.jsonl").write_bytes(b'{"state": "thinking"}\n')
            (evdir / "cursor.jsonl").write_bytes(b'{"state": "working"}\n')
            (evdir / "ci.jsonl").write_bytes(b'{"state": "error"}\n')
            time.sleep(0.3)
            n += check(link.get_state() == "error", "error (prio 5) 压过 working/thinking")
            agents = link.get_agents()
            n += check(set(agents) == {"claude", "cursor", "ci"}, "3 个 agent 都被发现")
            n += check(agents["claude"][0] == "thinking" and agents["cursor"][0] == "working"
                       and agents["ci"][0] == "error", "每个 agent 独立记录")
        finally:
            link.stop()
    return n


def test_file_lifecycle():
    section("文件新增 / 删除 / 轮转")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        link = AgentLink(cfg, poll_sec=0.05, stale_sec=10.0)
        link.start()
        try:
            time.sleep(0.15)
            evdir = cfg / "agent-events"
            evdir.mkdir(parents=True, exist_ok=True)
            # 新增
            (evdir / "alpha.jsonl").write_bytes(b'{"state": "thinking"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "thinking", "新文件 alpha 被检测")
            # 删除
            (evdir / "alpha.jsonl").unlink()
            time.sleep(0.2)
            n += check(link.get_state() == "idle", "文件被删 → 该 agent 状态回收 → 聚合 idle")
            # 重新创建并轮转（写 → 截断 → 再写）
            (evdir / "alpha.jsonl").write_bytes(b'{"state": "working"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "working", "重建后 working 重新生效")
            # 截断（轮转模拟）
            (evdir / "alpha.jsonl").write_bytes(b'{"state": "error"}\n')
            time.sleep(0.2)
            n += check(link.get_state() == "error", "截断后新内容被识别")
        finally:
            link.stop()
    return n


def test_callback_dedup():
    section("callback 仅在聚合态变化时触发")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        link = AgentLink(cfg, poll_sec=0.05, stale_sec=10.0)
        seen = []
        link.set_callback(lambda s, a: seen.append(s))
        link.start()
        try:
            time.sleep(0.15)
            f = cfg / "agent-events" / "x.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "ab") as out:
                # 写 5 行同 state → callback 只触发 1 次
                for _ in range(5):
                    out.write(b'{"state": "thinking"}\n')
            time.sleep(0.3)
            n += check(seen.count("thinking") == 1, f"5 次同 state 写入只触发 1 次回调（实际 {seen.count('thinking')}）")
            # 再写一个不同 state → 再触发 1 次
            with open(f, "ab") as out:
                out.write(b'{"state": "error"}\n')
            time.sleep(0.2)
            n += check(seen.count("error") == 1, "态迁移触发新回调")
            n += check(seen == ["thinking", "error"], f"回调顺序正确: {seen}")
        finally:
            link.stop()
    return n


def test_idempotent_start_stop():
    section("start/stop 幂等")
    n = 0
    with tempfile.TemporaryDirectory() as tmp:
        cfg = Path(tmp)
        link = AgentLink(cfg)
        link.start()
        n += check(link.is_running(), "start 后 is_running")
        link.start()  # 重复 start 不报错
        n += check(link.is_running(), "重复 start 仍 running")
        link.stop()
        n += check(not link.is_running(), "stop 后 not running")
        link.stop()  # 重复 stop 不报错
        n += check(not link.is_running(), "重复 stop 仍 not running")
    return n


def test_pure_logic_no_qt():
    section("纯逻辑层：无 PySide6 import 语句")
    import agent_link as al
    import re
    src = Path(al.__file__).read_text(encoding="utf-8")
    bad = re.findall(r"^\s*(?:import\s+PySide6|from\s+PySide6|import\s+PyQt|from\s+PyQt|import\s+qtpy|from\s+qtpy)",
                     src, re.MULTILINE)
    n = check(not bad, f"无 Qt import 语句（实际找到 {len(bad)} 处）")
    return n


def main():
    print("=" * 60)
    print("T9 Agent Link 验收")
    print("=" * 60)
    fails = 0
    total_checks = 0
    fails += test_normalize_event()
    fails += test_offset_and_bad_inputs()
    fails += test_stale_ttl()
    fails += test_multi_agent_aggregation()
    fails += test_file_lifecycle()
    fails += test_callback_dedup()
    fails += test_idempotent_start_stop()
    fails += test_pure_logic_no_qt()
    # 重新算总数（用上面累加得到的失败数 反推不靠谱，干脆重数）
    # 简化：直接 grep 这次跑出来的 PASS/FAIL 数量不现实，main 自己维护一个清单太啰嗦
    # 干脆让 fails 含义保持"实际失败项数"，并打印总项数
    print()
    # 注：上面累加的 fails 是真实失败数（check 已修）
    if fails == 0:
        print(f"ALL PASS · agent_link 模块行为符合需求定稿")
        return 0
    print(f"FAIL · 有 {fails} 项不通过")
    return 1


if __name__ == "__main__":
    sys.exit(main())
