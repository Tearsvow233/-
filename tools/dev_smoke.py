# -*- coding: utf-8 -*-
"""BabyCat M5 最小开发冒烟：不依赖 main.main()，直接构造 PetWindow 做基础检查。
用法：python tools/dev_smoke.py
可保留：后续开发/打包前快速回归用。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 便于从项目根 import main
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


def main_smoke():
    s = m.load_settings()
    s["pos_x"] = 100
    s["pos_y"] = 100
    s["mode"] = "normal"
    s["sleep_after_min"] = 1  # 便于手动 go_sleep 测试；_check_sleep 有 60s 门槛不会立刻触发

    app = m.QApplication.instance() or m.QApplication(sys.argv)

    w = m.PetWindow(s)
    w.show()
    print("INIT OK", w.state, sorted(w.action_frames.keys()))
    check("init_state_idle", w.state == "idle", w.state)
    for k in ("pace", "spin", "recoil", "sleep", "wake", "walk_circle"):
        check(f"action_loaded_{k}", k in w.action_frames, len(w.action_frames.get(k, [])))

    # ---- 入睡状态机：直接 go_sleep（跳过 60s 超时）----
    w.go_sleep()
    print("after go_sleep -> state=%s pending=%s action=%s" % (
        w.state, w._sleep_pending, w.action_name))
    check("go_sleep_entered", w._sleep_pending and w.action_name == "sleep",
          (w.state, w._sleep_pending, w.action_name))

    # 手动驱动 action_step 播完入睡序列 → 应落定 sleep 且停在末帧
    steps = 0
    while w.state != "sleep" and steps < 500:
        w.action_step()
        steps += 1
    check("sleep_seq_finishes_to_sleep", w.state == "sleep" and not w._sleep_pending,
          (w.state, w._sleep_pending))
    check("sleep_no_auto_timers", not w.action_timer.isActive()
          and not w.blink_timer.isActive() and not w.behavior_timer.isActive()
          and not w.chatter_timer.isActive())

    # 睡眠态防御守卫：外部直接调用闲聊/自动动作入口 → 直接 return，
    # 不弹气泡也不重排任何自动行为定时器（QA B2 观察项）
    w.idle_chatter()
    check("guard_idle_chatter_in_sleep", w.state == "sleep"
          and not w.chatter_timer.isActive(), (w.state, w.chatter_timer.isActive()))
    w.maybe_auto_action()
    check("guard_maybe_auto_in_sleep", w.state == "sleep"
          and not w.auto_action_timer.isActive() and w.action_name is None,
          (w.state, w.auto_action_timer.isActive(), w.action_name))
    w.schedule_next_auto_action()
    check("guard_sched_auto_in_sleep", not w.auto_action_timer.isActive(),
          w.auto_action_timer.isActive())

    # 睡眠中普通点击不应触发反应
    from PySide6.QtCore import Qt, QPoint
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtCore import QEvent
    def fake_press_release(w_):
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPoint(5, 5),
                         QPoint(5, 5), Qt.MouseButton.LeftButton,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        w_.mousePressEvent(ev)
        ev2 = QMouseEvent(QEvent.Type.MouseButtonRelease, QPoint(5, 5),
                          QPoint(5, 5), Qt.MouseButton.LeftButton,
                          Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        w_.mouseReleaseEvent(ev2)
    fake_press_release(w)
    check("click_in_sleep_no_react", w.state == "sleep"
          and w.action_name is None and w._wake_click_count == 1,
          (w.state, w._wake_click_count))

    # 三连击唤醒
    w._wake_click_count = 2
    fake_press_release(w)
    print("after 3rd click -> state=%s action=%s pending=%s count=%s" % (
        w.state, w.action_name, w._sleep_pending, w._wake_click_count))
    check("triple_click_wakes", w.action_name == "wake" and w._wake_click_count == 0,
          (w.state, w.action_name, w._wake_click_count))

    # 播完 wake → 淡出回 idle（驱动 action_timer 直到停下）
    steps = 0
    while w.action_timer.isActive() and steps < 2000:
        w.action_step()
        steps += 1
    check("wake_anim_returns_idle", w.state == "idle" and w.action_name is None,
          (w.state, w.action_name))

    # ---- _check_sleep 路径：把 last_touch 改老，模拟 sleep_check_timer 触发 ----
    w.settings["sleep_after_min"] = 1
    w.last_touch_ts = time.time() - 61   # 模拟 61 秒无互动（1 分钟阈值）
    w._check_sleep()
    print("after _check_sleep -> state=%s pending=%s action=%s" % (
        w.state, w._sleep_pending, w.action_name))
    check("check_sleep_triggers", w._sleep_pending and w.action_name == "sleep",
          (w.state, w._sleep_pending, w.action_name))
    # 收尾：唤醒并播完回 idle，避免残留影响后续用例
    w.wake_up()
    steps = 0
    while w.action_timer.isActive() and steps < 2000:
        w.action_step()
        steps += 1
    check("cleanup_to_idle", w.state == "idle", (w.state, w.action_name))
    w.settings["sleep_after_min"] = 1

    # ---- 点击反馈动作池（start_react）----
    seen = set()
    for _ in range(30):
        w.start_react()
        if w.action_name:
            seen.add(w.action_name)
        # 播一小段后直接强制收尾，避免残留定时器
        steps = 0
        while w.action_timer.isActive() and steps < 60:
            w.action_step()
            steps += 1
    print("click pool seen:", sorted(seen))
    check("click_pool_subset", seen <= {"recoil", "spin", "walk_circle"}, sorted(seen))
    check("click_pool_multi", len(seen) > 1, sorted(seen))

    # ---- 灵宠中心能正常构造（含入睡等待 spin + 模板按钮）----
    dlg = m.PetCenter(s, w)
    print("PetCenter values keys:", sorted(k for k in dlg.values().keys()
                                          if k in ("sleep_after_min", "water_min", "sit_min")))
    check("petcenter_has_sleep", dlg.values().get("sleep_after_min") == 1)
    check("petcenter_no_legacy", "water_min" not in dlg.values()
          and "sit_min" not in dlg.values())
    dlg.deleteLater()

    # ---- 旧配置迁移（打桩 save_settings，避免污染 settings.json）----
    orig_save = m.save_settings
    saved_calls = []
    m.save_settings = lambda cfg: saved_calls.append(dict(cfg))
    try:
        cfg = {"water_min": 40, "sit_min": 30, "reminders": [{"name": "喝水",
                                                              "enabled": True}]}
        m.migrate_legacy_reminders(cfg)
        names = [r.get("name") for r in cfg["reminders"]]
        check("migrate_appends", "起来活动一下" in names and len(saved_calls) == 1, names)
        check("migrate_dedupe", names.count("喝水") == 1, names)
        check("migrate_pops_old", "water_min" not in cfg and "sit_min" not in cfg)
        # 二次运行幂等：不追加、不再写盘
        before = len(saved_calls)
        cfg2 = {"reminders": [{"name": "喝水", "enabled": True},
                              {"name": "起来活动一下", "enabled": True}]}
        m.migrate_legacy_reminders(cfg2)
        check("migrate_idempotent", len(saved_calls) == before, len(saved_calls) - before)
    finally:
        m.save_settings = orig_save

    # ---- 提醒触发文案分类（含喝水关键词走 WATER_TEXTS）----
    fired = []
    orig_say = w.bubble.say
    w.bubble.say = lambda txt, *a, **k: fired.append(txt)
    w.settings["reminders"] = [{"name": "喝水", "mode": "interval",
                                "interval_min": 5, "once": False, "enabled": True},
                               {"name": "起来活动一下", "mode": "interval",
                                "interval_min": 5, "once": False, "enabled": True},
                               {"name": "交作业", "mode": "interval",
                                "interval_min": 5, "once": False, "enabled": True}]
    for idx in range(3):
        w.fire_custom_reminder(idx)
    w.bubble.say = orig_say
    check("reminder_texts_fired", len(fired) == 3, fired)

    w.close()
    print("\nSMOKE RESULT:", "ALL PASS" if not failures else
          f"{len(failures)} FAILED: {failures}")


if __name__ == "__main__":
    main_smoke()
    sys.exit(1 if failures else 0)
