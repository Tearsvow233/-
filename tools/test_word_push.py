# -*- coding: utf-8 -*-
"""每日英语单词推送 —— 新增功能离屏单测（可重复运行，不污染真实 settings/progress）。

用法：python tools/test_word_push.py
覆盖：数据完整性 / 每日一次不重复 / 词量 5~20 / date 种子连续 N 词轮转 /
      WordCardDialog 内容与标题 / 入睡态被推→was_sleeping 路径 /
      词卡关闭恢复睡眠 / 托盘回看 / 跨日重置 / 模态跳过 / 词库缺失兜底。
"""
import os
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m            # noqa: E402
import word_push as wp      # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


def drive_until(w_, cond, max_steps=3000):
    n = 0
    while not cond() and n < max_steps:
        w_.action_step()
        n += 1
    return n


def labels_text(widget):
    return " ".join(lb.text() for lb in widget.findChildren(m.QLabel))


def norm_text(t):
    return t.replace(" ", "").replace("；", "").replace("，", "")


def main_test():
    tmp = tempfile.mkdtemp(prefix="babycat_word_test_")
    progress_path = os.path.join(tmp, "words_progress.json")
    orig_progress = m.WORDS_PROGRESS_FILE
    orig_save = m.save_settings
    m.WORDS_PROGRESS_FILE = progress_path
    m.save_settings = lambda cfg: None   # 测试期间不写真实 settings.json
    w = None
    card = None
    try:
        s = m.load_settings()
        s["pos_x"], s["pos_y"] = 100, 100
        s["mode"] = "normal"
        s["sleep_after_min"] = 1
        s["auto_walk"] = True
        s["word_enabled"] = True
        s["word_count"] = 10
        app = m.QApplication.instance() or m.QApplication(sys.argv)
        w = m.PetWindow(s)
        w.show()

        # ========== 1) 词库数据完整性 ==========
        words = wp.load_words()
        print("word lib size:", len(words))
        check("data_count_ge_1000", len(words) >= 1000, len(words))
        check("data_fields_nonempty",
              all(d.get("word") and d.get("phonetic") and d.get("meaning")
                  for d in words))
        check("data_unique_word",
              len({d["word"].lower() for d in words}) == len(words))
        check("load_missing_file_ok", wp.load_words(os.path.join(tmp, "nope.json")) == [])

        # ========== 2) date 种子选词：确定性 / 连续 N / 不重复 / 轮转 ==========
        syn = [{"word": f"w{i}", "phonetic": "/p%d/" % i, "meaning": "义%d" % i}
               for i in range(20)]
        d1 = wp.pick_words(syn, "2026-01-01", 5)     # epoch 偏移 0 → w0..w4
        d1b = wp.pick_words(syn, "2026-01-01", 5)
        d2 = wp.pick_words(syn, "2026-01-02", 5)     # 前进 5 → w5..w9
        d5 = wp.pick_words(syn, "2026-01-05", 5)     # 满一轮回到 w0..w4
        check("pick_deterministic", d1 == d1b and [x["word"] for x in d1] ==
              ["w0", "w1", "w2", "w3", "w4"], [x["word"] for x in d1])
        check("pick_advance_by_count", [x["word"] for x in d2] ==
              ["w5", "w6", "w7", "w8", "w9"])
        check("pick_cycle_full_table", [x["word"] for x in d5] ==
              ["w0", "w1", "w2", "w3", "w4"])
        check("pick_no_dup_within_day",
              len({x["word"] for x in wp.pick_words(syn, "2026-03-11", 8)}) == 8)
        # count 超过总长 → 收敛到总长，不产生重复
        check("pick_count_clamped",
              len(wp.pick_words(syn, "2026-03-11", 25)) == 20)
        # 真实词库：取 10/12 词均无同日重复
        for c in (5, 10, 12, 20):
            day = wp.pick_words(words, "2026-03-11", c)
            check("real_pick_count_%d_no_dup" % c,
                  len(day) == c and len({x["word"] for x in day}) == c, len(day))

        # ========== 3) 每日一次 / 跨日重置（纯函数层） ==========
        prog_old = {"date": "2020-01-01", "pushed": True, "words": words[:3]}
        check("pushed_today_false_olddate",
              not wp.pushed_today(prog_old), prog_old["date"])
        day_words, prog_new = wp.plan_words(words, prog_old, None, 10)
        check("plan_newday_rolls", len(day_words) == 10
              and prog_new["date"] == wp.today_str() and prog_new["pushed"])
        day_words2, prog2 = wp.plan_words(words, prog_new, None, 10)
        check("plan_sameday_reuse",
              day_words2 == day_words and prog2["date"] == prog_new["date"])

        # ========== 4) WordCardDialog：标题不含宠物名 + 词/音标/释义 ==========
        pet_name = s["pet_name"]
        card = wp.WordCardDialog(words[:3], title="每日单词")
        card.show()
        check("card_title_no_petname",
              "每日单词" in card.windowTitle() and pet_name not in card.windowTitle(),
              (card.windowTitle(), pet_name))
        texts = norm_text(labels_text(card))
        for d in words[:3]:
            check("card_contains_%s" % d["word"],
                  norm_text(d["word"]) in texts and norm_text(d["meaning"])[:6] in texts,
                  d["word"])
        check("card_phonetic_shown", "/" in labels_text(card), labels_text(card)[:60])
        check("card_words_prop", card.words == words[:3])
        card.reject()          # finished -> 但 was_sleeping=False 不恢复睡眠
        card = None
        w._word_card = None

        # ========== 5) PetCenter：每日单词区块（开关 + 词量 5~20） ==========
        dlg = m.PetCenter(s, w)
        check("center_word_spin_range",
              dlg.word_spin.minimum() == 5 and dlg.word_spin.maximum() == 20
              and dlg.word_spin.value() == int(s.get("word_count", 10)),
              (dlg.word_spin.minimum(), dlg.word_spin.maximum(), dlg.word_spin.value()))
        dlg.word_spin.setValue(7)
        vals = dlg.values()
        check("center_values_new_keys",
              vals.get("word_enabled") is True and vals.get("word_count") == 7,
              (vals.get("word_enabled"), vals.get("word_count")))
        dlg.deleteLater()

        # ========== 6) 调度：启动窗口 + 空闲巡检的启停 ==========
        w.setup_word_push()
        check("start_timer_armed",
              w.word_start_timer.isActive()
              and w.word_start_timer.interval() == 3 * 60 * 1000,
              w.word_start_timer.interval())
        check("idle_timer_armed",
              w.word_idle_timer.isActive()
              and w.word_idle_timer.interval() == 45 * 1000,
              w.word_idle_timer.interval())
        w.settings["word_enabled"] = False
        w.setup_word_push()
        check("disable_stops_timers",
              not w.word_start_timer.isActive() and not w.word_idle_timer.isActive())
        w.settings["word_enabled"] = True
        w.setup_word_push()

        # ========== 7) 推送入口：当天已推不再推 / 模态中跳过 ==========
        w._try_push_daily_words("test")
        if w._word_card is not None:
            w._word_card.reject()
            w._word_card = None
        check("pushed_once_saved", wp.pushed_today(
            wp.load_progress(progress_path)))
        # 已推状态再调入口 → 不重复弹卡
        before = w._word_card
        ok2 = w._try_push_daily_words("again")
        check("no_second_push_sameday", ok2 is False and w._word_card is before)
        # 模拟模态窗口：清空当天进度后，startup tick 应跳过
        wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                         "words": []})
        w._word_modal_busy = lambda: True
        w._word_startup_tick()
        w._word_modal_busy = lambda: False
        check("modal_busy_skips", not wp.pushed_today(
            wp.load_progress(progress_path)))
        del w._word_modal_busy

        # ========== 8) 入睡态被推：was_sleeping → 唤醒表现 + 弹卡；关闭后睡回 ==========
        w.go_sleep()
        steps = drive_until(w, lambda: w.state == "sleep" and not w._sleep_pending)
        check("pre_sleep_for_push", w.state == "sleep", (w.state, steps))
        pushed = w._try_push_daily_words("sleep_test")
        check("sleep_push_executed", pushed is True and w._word_card is not None)
        card2 = w._word_card
        check("sleep_wake_look", w.action_name == "wake" or w.state == "idle"
              or w.state == "action",
              (w.state, w.action_name))
        # 关闭词卡 → 应自动恢复睡眠画面（不重启自动定时器）
        card2.reject()
        check("card_close_restores_sleep",
              w.state == "sleep" and not w._sleep_pending,
              (w.state, w._sleep_pending))
        check("restore_no_auto_timers",
              not w.blink_timer.isActive() and not w.behavior_timer.isActive()
              and not w.chatter_timer.isActive()
              and not w.auto_action_timer.isActive(),
              (w.blink_timer.isActive(), w.behavior_timer.isActive(),
               w.chatter_timer.isActive(), w.auto_action_timer.isActive()))

        # ========== 9) 托盘回看：当天已推 → 弹「今日单词」卡 ==========
        said = []
        w.bubble.say = lambda txt, *a, **k: said.append(txt)
        w.open_today_words()
        check("tray_review_card_open", w._word_card is not None
              and w._word_card.windowTitle() == "今日单词",
              w._word_card.windowTitle() if w._word_card else None)
        if w._word_card is not None:
            w._word_card.reject()
            w._word_card = None
        # 当天未推 → 气泡提示，不弹卡
        wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                         "words": []})
        w.open_today_words()
        check("tray_review_empty_bubbles",
              w._word_card is None and len(said) >= 1
              and "还没" in said[-1], said[-1:])
        w.bubble.say = lambda txt, *a, **k: None

        # ========== 10) 词库缺失兜底：气泡一次，不崩溃、调度停止 ==========
        said2 = []
        w.bubble.say = lambda txt, *a, **k: said2.append(txt)
        orig_load = wp.load_words
        wp.load_words = lambda *a, **k: []
        try:
            wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                             "words": []})
            r = w._try_push_daily_words("missing")
            check("missing_lib_no_crash", r is False and len(said2) == 1
                  and "单词库没装上" in said2[0], said2[:1])
            check("missing_lib_stops_schedule",
                  not w.word_start_timer.isActive()
                  and not w.word_idle_timer.isActive())
        finally:
            wp.load_words = orig_load
            w.bubble.say = lambda txt, *a, **k: None

        w.close()
    finally:
        m.save_settings = orig_save
        m.WORDS_PROGRESS_FILE = orig_progress
        try:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass

    print("\nWORD PUSH TEST RESULT:", "ALL PASS" if not failures else
          f"{len(failures)} FAILED: {failures}")


if __name__ == "__main__":
    main_test()
    sys.exit(1 if failures else 0)
