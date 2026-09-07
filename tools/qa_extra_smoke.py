# -*- coding: utf-8 -*-
"""QA 独立回归补充用例：覆盖 dev_smoke 未触及的路径。

仅验证，不修改 main.py 源码。可安全重跑（不写真实 settings.json）。
用法：python tools/qa_extra_smoke.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m  # noqa: E402

failures = []
warns = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


def note(text):
    print("NOTE " + text)
    warns.append(text)


def press(w_, x=5, y=5):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    w_.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPoint(x, y), QPoint(x, y),
                                   Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                                   Qt.KeyboardModifier.NoModifier))


def release(w_, x=5, y=5):
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    w_.mouseReleaseEvent(QMouseEvent(QEvent.Type.MouseButtonRelease, QPoint(x, y), QPoint(x, y),
                                     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                                     Qt.KeyboardModifier.NoModifier))


def click(w_, x=5, y=5):
    press(w_, x, y)
    release(w_, x, y)


def drive_until(w_, cond, max_steps=3000):
    n = 0
    while not cond() and n < max_steps:
        w_.action_step()
        n += 1
    return n


def main_qa():
    s = m.load_settings()
    # 载入真实 settings 仅用于构造对象；所有写盘入口被桩掉
    orig_save = m.save_settings
    m.save_settings = lambda cfg: None
    try:
        s["pos_x"] = 100
        s["pos_y"] = 100
        s["mode"] = "normal"
        s["sleep_after_min"] = 0          # 本轮先关闭入睡，专注点击池
        s["auto_walk"] = True
        s["reminders"] = []
        app = m.QApplication.instance() or m.QApplication(sys.argv)
        w = m.PetWindow(s)
        w.show()

        # ========== B3a: 点击池确定性验证 ==========
        # 固定 random.choices → 检查每次都命中候选集且播放了
        calls = []
        orig_choices = m.random.choices
        m.random.choices = lambda population, weights=None, k=1: [population[0]]
        try:
            w.settings["sleep_after_min"] = 0
            for _ in range(20):
                before = w.action_name
                w.start_react()
                act = w.action_name
                check("b3_pool_always_plays", act in ("recoil", "spin", "walk_circle"),
                      (before, act))
                # 收尾（可能已处于 action，把它播完回到 idle 以免干扰下一轮）
                drive_until(w, lambda: w.action_name is None and w.state == "idle")
            # 顺序应该第一候选是 recoil（pool 顺序 recoil, spin, walk_circle）
        finally:
            m.random.choices = orig_choices

        # ========== B3b: action_frames 只留 recoil → 池过滤后只能出 recoil ==========
        w._sleep_pending = False
        saved_af = dict(w.action_frames)
        w.action_frames = {k: v for k, v in saved_af.items() if k == "recoil"}
        for _ in range(5):
            w.start_react()
            check("b3_pool_filters_recoil", w.action_name == "recoil", w.action_name)
            drive_until(w, lambda: w.action_name is None and w.state == "idle")
        w.action_frames = saved_af

        # ========== B3c: 候选全部无素材 → 回退 play_bounce ==========
        w.action_frames = {k: v for k, v in saved_af.items()
                           if k not in ("recoil", "spin", "walk_circle")}
        w.start_react()
        check("b3_pool_empty_fallback_bounce",
              w.state == "action" and w.action_name == "_bounce",
              (w.state, w.action_name))
        # 收尾回 idle（bounce 走 action_step 会收尾）
        drive_until(w, lambda: w.action_name is None and w.state == "idle")
        w.action_frames = saved_af

        # ========== 入睡 & 唤醒（含定时器恢复） ==========
        w.settings["sleep_after_min"] = 1
        # 确保 idle 态下自动定时器本来活着
        drive_until(w, lambda: w.action_name is None)
        w.go_sleep()
        steps = drive_until(w, lambda: w.state == "sleep" and not w._sleep_pending)
        check("qa_sleep_landed", w.state == "sleep", (w.state, steps))
        check("qa_sleep_all_timers_stopped",
              not w.action_timer.isActive() and not w.blink_timer.isActive()
              and not w.behavior_timer.isActive() and not w.chatter_timer.isActive()
              and not w.auto_action_timer.isActive(),
              (w.action_timer.isActive(), w.blink_timer.isActive(),
               w.behavior_timer.isActive(), w.chatter_timer.isActive(),
               w.auto_action_timer.isActive()))

        # ---- B2: sleep 态下直接调用 idle_chatter / maybe_auto_action ----
        said = []
        w.bubble.say = lambda txt, *a, **k: said.append(txt)
        # 先记录：两个方法都不应弹话 / 不应播放动作
        w.idle_chatter()
        w.maybe_auto_action()
        check("b2_no_speak_no_act_in_sleep",
              len(said) == 0 and w.action_name is None and w.state == "sleep",
              (len(said), w.action_name, w.state))
        # 防御面观察：idle_chatter/maybe_auto_action 是否会重启自动定时器（可达性另行分析）
        if w.chatter_timer.isActive() or w.auto_action_timer.isActive():
            note("sleep 态直接调用 idle_chatter/maybe_auto_action 会重排空转定时器 "
                 "(chatter=%s auto_action=%s)；正常状态机下不可达，需做可达性判定"
                 % (w.chatter_timer.isActive(), w.auto_action_timer.isActive()))
        # 清理这两个被唤醒的定时器，保持后续用例干净
        w.chatter_timer.stop()
        w.auto_action_timer.stop()
        w.bubble.say = lambda txt, *a, **k: None

        # ---- 双击唤醒（monkeypatch open_chat_input，避免真对话框阻塞） ----
        opened = []
        w.open_chat_input = lambda: opened.append(1)
        # sleep 态直接构造 double-click 事件
        from PySide6.QtCore import Qt, QPoint, QEvent
        from PySide6.QtGui import QMouseEvent
        dbl = QMouseEvent(QEvent.Type.MouseButtonDblClick, QPoint(5, 5), QPoint(5, 5),
                          Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                          Qt.KeyboardModifier.NoModifier)
        w.mouseDoubleClickEvent(dbl)
        check("dbl_click_wakes_and_opens_chat",
              w._sleep_pending is False and opened == [1] and w.action_name == "wake",
              (w.state, w.action_name, len(opened)))
        # 播完 wake → idle + 自动定时器恢复
        drive_until(w, lambda: w.action_name is None and w.state == "idle")
        check("qa_wake_auto_timers_restored",
              w.blink_timer.isActive() and w.behavior_timer.isActive()
              and w.chatter_timer.isActive() and w.auto_action_timer.isActive(),
              (w.blink_timer.isActive(), w.behavior_timer.isActive(),
               w.chatter_timer.isActive(), w.auto_action_timer.isActive()))
        # 还原 open_chat_input（重绑原始 bound method）
        del w.open_chat_input

        # ---- 拖拽唤醒（先入睡再拖） ----
        w.go_sleep()
        drive_until(w, lambda: w.state == "sleep" and not w._sleep_pending)
        check("drag_pre_sleep", w.state == "sleep")
        # press 后大距离 move（>6px）→ 应先唤醒再进入拖拽
        press(w, 30, 30)
        w._press_pos = w._press_pos  # noqa：press 会记录 global pos
        mv = QMouseEvent(QEvent.Type.MouseMove, QPoint(80, 80), QPoint(80, 80),
                         Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.NoModifier)
        w.mouseMoveEvent(mv)
        # 拖拽分支会 stop action_timer & 置 state=drag；若 wake_up 已触发则 _sleep_pending 已清
        check("drag_wakes_from_sleep",
              w._sleep_pending is False and not w._is_sleeping(),
              (w.state, w._sleep_pending))
        release(w, 80, 80)
        check("drag_release_to_idle",
              w.state == "idle" and w.action_name is None,
              (w.state, w.action_name))
        # 拖拽完应恢复自动行为（走 mouseReleaseEvent 非 sleep 分支）
        check("qa_drag_timers_restored",
              w.behavior_timer.isActive() and w.blink_timer.isActive(),
              (w.behavior_timer.isActive(), w.blink_timer.isActive()))

        # ========== B4: 迁移补充（幂等 / 空 dict / 已有同名时只迁另一条） ==========
        saved = []
        m.save_settings = lambda cfg: saved.append(dict(cfg))
        # (a) 已有「喝水」提醒 + 旧键 → 只追加「起来活动一下」，写盘一次
        saved.clear()
        cfg = {"water_min": 40, "sit_min": 30,
               "reminders": [{"name": "喝水", "enabled": True}]}
        changed = m.migrate_legacy_reminders(cfg)
        names = [r["name"] for r in cfg["reminders"]]
        check("b4_partial_migrate", changed and "喝水" in names
              and "起来活动一下" in names and len(names) == 2,
              (names, len(saved)))
        check("b4_partial_save_once", len(saved) == 1, len(saved))
        check("b4_old_keys_removed", "water_min" not in cfg and "sit_min" not in cfg)
        # (b) 空 dict：安全，不抛异常，不写盘
        saved.clear()
        empty = {}
        try:
            changed2 = m.migrate_legacy_reminders(empty)
            ok_empty = True
        except Exception as e:
            ok_empty = False
            note("empty dict migrate raised: %r" % e)
        # setdefault 会补 reminders:[] 属正常副作用；核心是安全、不写盘、无残留旧键
        check("b4_empty_safe", ok_empty and changed2 is False
              and len(saved) == 0 and "water_min" not in empty
              and "sit_min" not in empty and empty.get("reminders") == [],
              (ok_empty, changed2, len(saved), empty))
        # (c) 完全迁移后的 dict 再来一次 → 幂等（不写盘）
        saved.clear()
        done = {"reminders": [{"name": "喝水", "enabled": True},
                              {"name": "起来活动一下", "enabled": True}]}
        changed3 = m.migrate_legacy_reminders(done)
        check("b4_done_idempotent", changed3 is False and len(saved) == 0
              and len(done["reminders"]) == 2, (changed3, len(saved)))
        m.save_settings = orig_save

        # ========== B5: 文案分流强断言 ==========
        fired = []
        w.bubble.say = lambda txt, *a, **k: fired.append(txt)
        w.settings["reminders"] = [{"name": "喝水", "mode": "interval",
                                    "interval_min": 5, "once": False, "enabled": True},
                                   {"name": "起来活动一下", "mode": "interval",
                                    "interval_min": 5, "once": False, "enabled": True},
                                   {"name": "下课", "mode": "interval",
                                    "interval_min": 5, "once": False, "enabled": True}]
        for idx in range(3):
            w.fire_custom_reminder(idx)
        fmt_water = [t.format(name=w.name()) for t in m.WATER_TEXTS]
        fmt_sit = [t.format(name=w.name()) for t in m.SIT_TEXTS]
        check("b5_water_text_pool", fired[0] in fmt_water, fired[0])
        check("b5_sit_text_pool", fired[1] in fmt_sit, fired[1])
        check("b5_generic_text_has_name",
              fired[2] not in fmt_water and fired[2] not in fmt_sit
              and "下课" in fired[2], fired[2])

        # ========== C2: PetCenter sleep_spin 细节 ==========
        dlg = m.PetCenter(s, w)
        ss = dlg.sleep_spin
        check("c2_sleep_spin_range", ss.minimum() == 0 and ss.maximum() == 120,
              (ss.minimum(), ss.maximum()))
        check("c2_special_value_text", ss.specialValueText() == "关闭",
              ss.specialValueText())
        ss.setValue(0)
        check("c2_zero_shows_off_text", ss.text() == "关闭", ss.text())
        vals = dlg.values()
        check("c2_values_has_sleep_no_legacy",
              "sleep_after_min" in vals and vals["sleep_after_min"] == 0
              and "water_min" not in vals and "sit_min" not in vals,
              sorted(k for k in vals if "min" in k))
        dlg.deleteLater()

        w.close()
        m.save_settings = orig_save
    finally:
        m.save_settings = orig_save

    print("\nEXTRA SMOKE RESULT:", "ALL PASS" if not failures else
          f"{len(failures)} FAILED: {failures}")
    if warns:
        print("OBSERVATIONS (%d):" % len(warns))
        for x in warns:
            print("  -", x)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main_qa()
