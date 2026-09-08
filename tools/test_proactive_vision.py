# -*- coding: utf-8 -*-
"""T8 proactive 主动行为 —— 验收测试（独立运行版）。

运行：python tools/test_proactive_vision.py
覆盖：dHash 计算 / 汉明距离 / 闲置判定（边沿触发+重置）/ 冷却 /
      进程白名单（大小写/路径/空表）/ reply_vision 请求构造。
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proactive_vision import (IdleDetector, dhash, hamming, process_allowed,
                               DHASH_W, DHASH_H)

PASS, FAIL = "[PASS]", "[FAIL]"
_cnt = {"pass": 0, "fail": 0}


def check(cond, label):
    print(f"  {PASS if cond else FAIL} {label}")
    _cnt["pass" if cond else "fail"] += 1
    return cond


def section(name):
    print(f"\n=== {name} ====")


def test_dhash():
    section("dHash")
    # 全平图 → 全 0
    check(dhash([128] * (DHASH_W * DHASH_H)) == 0, "全平图 → 0")
    # 每行严格递减 → 每行 8 个差分全为 1 → 全 1（64 bit）
    row = list(range(9, 0, -1))           # 9..1：左 > 右恒成立
    check(dhash(row * DHASH_H) == (1 << 64) - 1, "全对比图 → 全 1")
    # 亮度整体平移不改变差分 → 哈希不变（dHash 对光照鲁棒的核心）
    check(dhash([10, 20, 30] * 24) == dhash([50, 60, 70] * 24),
          "整体亮度平移 → 哈希不变")
    try:
        dhash([0] * 10)
        check(False, "长度错误应抛 ValueError")
    except ValueError:
        check(True, "长度错误抛 ValueError")


def test_hamming():
    section("汉明距离")
    check(hamming(0, 0) == 0, "相同 → 0")
    check(hamming(0, 1) == 1, "差 1 bit → 1")
    check(hamming(0, (1 << 64) - 1) == 64, "全反 → 64")


def test_idle_detector():
    section("闲置判定（边沿触发）")
    d = IdleDetector(stable_ticks=3, max_distance=2, cooldown_sec=100)
    t = 1000.0
    h_stable = 0b10101010
    check(d.update(h_stable, t) is False, "第 1 帧：不触发（无前帧）")
    check(d.update(h_stable, t + 1) is False, "第 2 帧：连续 2 不足 3")
    check(d.update(h_stable, t + 2) is True, "第 3 帧：达到阈值 → 边沿触发")
    check(d.update(h_stable, t + 3) is False, "第 4 帧：持续闲置不再触发")
    check(d.is_idle() is True, "is_idle 反映当前态")

    # 画面动了 → 重新计
    d2 = IdleDetector(stable_ticks=2, max_distance=2, cooldown_sec=0)
    check(d2.update(0xFF, t) is False, "新检测器首帧不触发")
    check(d2.update(0x00, t + 1) is False, "画面大变 → 计数清零")
    check(d2.update(0x00, t + 2) is True, "稳定 2 帧 → 触发")

    # 参数校验
    try:
        IdleDetector(stable_ticks=0)
        check(False, "stable_ticks=0 应抛 ValueError")
    except ValueError:
        check(True, "stable_ticks=0 抛 ValueError")


def test_cooldown():
    section("冷却")
    d = IdleDetector(stable_ticks=1, max_distance=64, cooldown_sec=50)
    t = 2000.0
    check(d.in_cooldown(t) is False, "从未搭话 → 不在冷却")
    d.update(1, t)
    d.notify_chat(t + 10)
    check(d.in_cooldown(t + 20) is True, "搭话后 10s → 冷却中")
    check(d.in_cooldown(t + 59) is True, "搭话后 49s → 仍冷却")
    check(d.in_cooldown(t + 61) is False, "搭话后 51s > 50s → 冷却结束")
    # notify_chat 同时复位闲置状态（要重新观察满 stable_ticks，不是立即再触发）
    d3 = IdleDetector(stable_ticks=2, max_distance=64, cooldown_sec=50)
    d3.update(1, t)
    d3.notify_chat(t + 10)
    check(d3.update(1, t + 100) is False, "搭话后第 1 帧：重新观察，不触发")
    check(d3.update(1, t + 101) is True, "搭话后第 2 帧：再次满足 → 触发")


def test_whitelist():
    section("进程白名单（隐私红线）")
    wl = ["chrome", "Code.exe", " idea64 "]
    check(process_allowed("C:\\Program Files\\Google\\Chrome\\chrome.exe", wl) is True,
          "完整路径 + 白名单名（不带 exe）→ 命中")
    check(process_allowed("code.EXE", wl) is True, "大小写不敏感 → 命中")
    check(process_allowed("idea64.exe", wl) is True, "带空格的表项 → 命中")
    check(process_allowed("C:\\Windows\\system32\\cmd.exe", wl) is False,
          "不在白名单 → 拒绝")
    check(process_allowed(None, wl) is False, "None → 拒绝")
    check(process_allowed("chrome.exe", []) is False, "空白名单 → 全部拒绝")
    check(process_allowed("", wl) is False, "空进程名 → 拒绝")
    check(process_allowed("/usr/bin/code", ["code"]) is False,
          "Linux 无 .exe 后缀名不自动补（Windows 语义）→ 拒绝")


def test_reply_vision_payload():
    section("PetAI.reply_vision 请求构造（不发真网络）")
    import ai_chat

    captured = {}

    class _FakeResp:
        def __init__(self, obj):
            self._obj = obj
        def read(self):
            return json.dumps(self._obj).encode()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _FakeAI(ai_chat.PetAI):
        def __init__(self):
            super().__init__({"ai_enabled": True, "ai_api_key": "sk-test",
                              "ai_base_url": "https://fake/v1", "ai_model": "m1"})
        def reply_vision(self, image_b64, prompt, history=None, **kw):
            captured["b64"] = image_b64
            captured["prompt"] = prompt
            return "ok"

    fake = _FakeAI()
    img = base64.b64encode(b"\xff\xd8fakejpeg").decode()
    r = fake.reply_vision(img, "看一眼")
    check(r == "ok", "reply_vision 正常返回")
    check(captured["b64"] == img, "image_b64 原样传递")
    check(captured["prompt"] == "看一眼", "prompt 原样传递")

    # 未启用 → None（静默）
    off = ai_chat.PetAI({"ai_enabled": False})
    check(off.reply_vision(img, "x") is None, "AI 未启用 → None")

    # 真实 PetAI.reply_vision 的消息体格式（本地构造校验，不发包）
    real = ai_chat.PetAI({"ai_enabled": True, "ai_api_key": "k",
                          "ai_base_url": "https://fake/v1", "ai_model": "m",
                          "ai_vision_model": "vm"})
    import urllib.request
    orig_request = urllib.request.Request
    payload_box = {}

    def _spy_request(url, data=None, method=None):
        payload_box["data"] = json.loads(data.decode())
        payload_box["url"] = url
        raise OSError("stop here")

    urllib.request.Request = _spy_request
    try:
        real.reply_vision(img, "看一眼")
    except OSError:
        pass
    finally:
        urllib.request.Request = orig_request
    msgs = payload_box.get("data", {}).get("messages", [])
    ok_model = payload_box.get("data", {}).get("model") == "vm"
    ok_url = payload_box.get("url", "").endswith("/chat/completions")
    ok_img = (len(msgs) == 2 and isinstance(msgs[-1]["content"], list)
              and msgs[-1]["content"][1]["image_url"]["url"]
              .startswith("data:image/jpeg;base64,"))
    check(ok_model, "ai_vision_model 优先于 ai_model")
    check(ok_url, "走 /chat/completions 兼容路径")
    check(ok_img, "消息体是 OpenAI 视觉格式（text + image_url）")


def test_pure_logic_no_qt():
    section("纯逻辑层：无 PySide6 依赖")
    import proactive_vision as pv
    src = Path(pv.__file__).read_text(encoding="utf-8")
    n = check("import PySide6" not in src and "import PyQt" not in src,
              "proactive_vision.py 无 Qt import")
    return n


def main():
    print("=" * 60)
    print("T8 proactive 主动行为 验收")
    print("=" * 60)
    test_dhash()
    test_hamming()
    test_idle_detector()
    test_cooldown()
    test_whitelist()
    test_reply_vision_payload()
    test_pure_logic_no_qt()
    print()
    total = _cnt["pass"] + _cnt["fail"]
    if _cnt["fail"] == 0:
        print(f"ALL PASS · {total} 项全过")
        return 0
    print(f"FAIL · {total} 项中 {_cnt['fail']} 项不通过")
    return 1


if __name__ == "__main__":
    sys.exit(main())
