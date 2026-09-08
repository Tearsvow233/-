# -*- coding: utf-8 -*-
"""哈气动画门控测试：60s 未点击 → 下次点击播哈气（离屏，不真播视频）。

用法：python tools/test_hiss.py
覆盖：should_hiss 纯函数 / try_play 门控矩阵（超时、间隔内、睡眠、静默、
重复点击刷新时间戳、基线为进程启动时刻）/ PetWindow 集成（真实属性路径）。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m          # noqa: E402
import pet_hiss           # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


class FakePet:
    """最小宿主：只提供 try_play 需要的属性"""

    def __init__(self, mode="normal", sleeping=False):
        self.settings = {"mode": mode}
        self._sleeping = sleeping
        self.height = lambda: 150
        self.geometry = lambda: None
        self.screen = lambda: None

    def _is_sleeping(self):
        return self._sleeping


def with_stub_player(fn):
    """把模块级播放器换成记录桩，跑完还原"""
    calls = []

    class Stub:
        def play(self, pet):
            calls.append(pet)
            return True

    orig = pet_hiss._player
    pet_hiss._player = Stub()
    try:
        fn(calls)
    finally:
        pet_hiss._player = orig


def main_test():
    # ========== 1) should_hiss 纯函数 ==========
    now = 1000.0
    check("should_hiss_true_after_gap",
          pet_hiss.should_hiss(930.0, now=now, threshold=60.0))
    check("should_hiss_false_within_gap",
          not pet_hiss.should_hiss(950.0, now=now, threshold=60.0))
    check("should_hiss_boundary_equal",
          pet_hiss.should_hiss(940.0, now=now, threshold=60.0))
    check("should_hiss_bad_input", not pet_hiss.should_hiss(None, now=now))

    # ========== 2) try_play 门控矩阵（桩播放器） ==========
    def gate(calls):
        pet = FakePet()
        # 基线：无 _last_click_ts → 用 _app_start_ts；刚启动 → 不触发
        pet._app_start_ts = time.time()
        check("first_click_no_hiss",
              pet_hiss.try_play(pet) is False and not calls)
        # 点击后 1 秒再点 → 不触发，但时间戳已刷新
        t0 = pet._last_click_ts
        check("click_updates_ts", t0 is not None and time.time() - t0 < 5)
        check("rapid_click_no_hiss",
              pet_hiss.try_play(pet) is False and not calls)
        # 模拟 61 秒没点 → 触发
        pet._last_click_ts = time.time() - 61
        check("gap_click_hisses",
              pet_hiss.try_play(pet) is True and len(calls) == 1)
        # 播完立刻再点（时间戳刚被刷新）→ 不触发
        check("post_hiss_click_normal",
              pet_hiss.try_play(pet) is False and len(calls) == 1)
        # 睡眠中不哈气（优先唤醒语义）
        pet._last_click_ts = time.time() - 61
        pet._sleeping = True
        check("sleeping_no_hiss",
              pet_hiss.try_play(pet) is False and len(calls) == 1)
        pet._sleeping = False
        # 静默模式不哈气
        pet.settings["mode"] = "silent"
        check("silent_no_hiss",
              pet_hiss.try_play(pet) is False and len(calls) == 1)
        pet.settings["mode"] = "normal"
        # 从未点过（_last_click_ts 缺失）+ 启动超过 61s → 触发
        del pet._last_click_ts
        pet._app_start_ts = time.time() - 100
        check("no_click_since_launch_hisses",
              pet_hiss.try_play(pet) is True and len(calls) == 2)

    with_stub_player(gate)

    # ========== 3) 真实 PetWindow 集成 ==========
    s = m.load_settings()
    s["mode"] = "normal"
    app = m.QApplication.instance() or m.QApplication(sys.argv)
    w = m.PetWindow(s)
    w.show()

    def integ(calls):
        # PetWindow 有 _app_start_ts（单词功能引入，兼作哈气基线）
        w._app_start_ts = time.time() - 120
        if hasattr(w, "_last_click_ts"):
            del w._last_click_ts
        check("petwindow_attrs", hasattr(w, "_app_start_ts"))
        check("petwindow_try_play_true",
              pet_hiss.try_play(w) is True and len(calls) == 1)
        check("petwindow_ts_set",
              time.time() - w._last_click_ts < 5)
        # HISS_VIDEO 资源存在（开发态项目目录）
        check("video_resource_exists", pet_hiss.HISS_VIDEO.exists(),
              pet_hiss.HISS_VIDEO)

    with_stub_player(integ)
    w.close()

    print("\nHISS TEST RESULT:", "ALL PASS" if not failures else
          f"{len(failures)} FAILED: {failures}")


if __name__ == "__main__":
    main_test()
    sys.exit(1 if failures else 0)
