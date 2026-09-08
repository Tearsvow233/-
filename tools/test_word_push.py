# -*- coding: utf-8 -*-
"""每日英语单词推送 —— 离屏单测（可重复运行，不污染真实 settings/progress）。

用法：python tools/test_word_push.py
覆盖：数据完整性 / date 种子选词 / 每日一次与跨日重置 / 分批纯函数
（batches_for / batch_times / due_batch / 旧格式迁移）/ WordCardDialog 与
WordBubble 内容与发音链接 / 60s 巡检 tick 全流程（规划→到点推批→最小间隔）
/ 入睡态被推→was_sleeping 路径 / 托盘回看 / 词库缺失兜底。
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta

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
        for c in (5, 10, 12, 20):
            day = wp.pick_words(words, "2026-03-11", c)
            check("real_pick_count_%d_no_dup" % c,
                  len(day) == c and len({x["word"] for x in day}) == c, len(day))

        # ========== 3) 每日一次 / 跨日重置 / 批次字段 ==========
        prog_old = {"date": "2020-01-01", "pushed": True, "words": words[:3]}
        check("pushed_today_false_olddate", not wp.pushed_today(prog_old))
        day_words, prog_new = wp.plan_words(words, prog_old, None, 10)
        check("plan_newday_rolls", len(day_words) == 10
              and prog_new["date"] == wp.today_str() and prog_new["pushed"]
              and prog_new["batch_done"] == 0 and prog_new["last_push_ts"] == 0.0)
        day_words2, prog2 = wp.plan_words(words, prog_new, None, 10)
        check("plan_sameday_reuse",
              day_words2 == day_words and prog2["date"] == prog_new["date"])

        # ========== 4) 分批纯函数：batches_for / batch_times / due_batch ==========
        bt = wp.batches_for(words[:9])
        check("batches_split", len(bt) == 5 and [len(x) for x in bt] == [2, 2, 2, 2, 1])
        t5 = wp.batch_times("2026-09-08", 5)
        check("batch_times_count", len(t5) == 5)
        check("batch_times_window",
              all(datetime.strptime("2026-09-08 09:00", "%Y-%m-%d %H:%M") <= t
                  <= datetime.strptime("2026-09-08 20:30", "%Y-%m-%d %H:%M")
                  for t in t5), [t.strftime("%H:%M") for t in t5])
        check("batch_times_deterministic", t5 == wp.batch_times("2026-09-08", 5)
              and t5 != wp.batch_times("2026-09-09", 5))
        # due_batch：未规划 None / 未到点 None / 到点返回 / 最小间隔 / 推完 None
        prog_due = {"date": wp.today_str(), "pushed": True, "words": words[:4],
                    "batch_done": 0, "last_push_ts": 0.0}
        past = datetime.now() - timedelta(minutes=5)
        future = datetime.now() + timedelta(hours=2)
        orig_bt = wp.batch_times
        wp.batch_times = lambda d, n: [past] * n
        try:
            check("due_none_when_not_planned",
                  wp.due_batch({"date": wp.today_str(), "pushed": False,
                                "words": [], "batch_done": 0}) is None)
            check("due_returns_index", wp.due_batch(prog_due) == 0)
            prog_due["last_push_ts"] = time.time()
            check("due_min_gap_blocks", wp.due_batch(prog_due) is None)
            prog_due["last_push_ts"] = time.time() - wp.MIN_GAP_SEC - 1
            check("due_after_gap", wp.due_batch(prog_due) == 0)
            prog_due["batch_done"] = 2
            check("due_none_when_all_done", wp.due_batch(prog_due) is None)
        finally:
            wp.batch_times = orig_bt
        wp.batch_times = lambda d, n: [future] * n
        try:
            check("due_none_before_time",
                  wp.due_batch({"date": wp.today_str(), "pushed": True,
                                "words": words[:4], "batch_done": 0,
                                "last_push_ts": 0.0}) is None)
        finally:
            wp.batch_times = orig_bt
        # 旧格式迁移：无 batch_done + 已推 → 视为全部推完
        wp.save_progress(progress_path, {"date": wp.today_str(), "pushed": True,
                                         "words": words[:4]})
        mig = wp.load_progress(progress_path)
        check("legacy_progress_migrated", mig["batch_done"] == 2
              and wp.due_batch(mig) is None, mig["batch_done"])
        check("any_pushed_semantics",
              wp.any_pushed_today({"date": wp.today_str(), "pushed": True,
                                   "words": words[:4], "batch_done": 1})
              and not wp.any_pushed_today({"date": wp.today_str(), "pushed": True,
                                           "words": words[:4], "batch_done": 0}))
        check("words_pushed_so_far",
              wp.words_pushed_so_far({"date": wp.today_str(), "pushed": True,
                                      "words": words[:5], "batch_done": 2})
              == words[:4])

        # ========== 5) WordCardDialog：标题不含宠物名 + 可点发音链接 ==========
        pet_name = s["pet_name"]
        card = wp.WordCardDialog(words[:3], title="每日单词")
        card.show()
        check("card_title_no_petname",
              "每日单词" in card.windowTitle() and pet_name not in card.windowTitle())
        texts = norm_text(labels_text(card))
        for d in words[:3]:
            check("card_contains_%s" % d["word"],
                  norm_text(d["word"]) in texts and norm_text(d["meaning"])[:6] in texts,
                  d["word"])
        said_words = []
        orig_speak = wp.speak_word
        wp.speak_word = lambda w_: said_words.append(w_) or True
        try:
            wp._on_say_link("say:" + words[0]["word"])
            check("card_link_speaks", said_words == [words[0]["word"]], said_words)
        finally:
            wp.speak_word = orig_speak
        card.reject()
        card = None
        w._word_card = None

        # ========== 6) PetCenter：每日单词区块（开关 + 词量 5~20） ==========
        dlg = m.PetCenter(s, w)
        check("center_word_spin_range",
              dlg.word_spin.minimum() == 5 and dlg.word_spin.maximum() == 20
              and dlg.word_spin.value() == int(s.get("word_count", 10)))
        dlg.word_spin.setValue(7)
        vals = dlg.values()
        check("center_values_new_keys",
              vals.get("word_enabled") is True and vals.get("word_count") == 7)
        dlg.deleteLater()

        # ========== 7) 调度：60s 巡检定时器启停 ==========
        w.setup_word_push()
        check("word_timer_armed",
              w.word_timer.isActive() and w.word_timer.interval() == 60 * 1000,
              w.word_timer.interval())
        w.settings["word_enabled"] = False
        w.setup_word_push()
        check("disable_stops_timer", not w.word_timer.isActive())
        w.settings["word_enabled"] = True
        w.setup_word_push()

        # ========== 8) tick 全流程：宽限→规划→到点推批→最小间隔 ==========
        wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                         "words": []})
        w._word_tick()   # 启动 3 分钟宽限内：什么都不做
        check("startup_grace_no_plan", not wp.pushed_today(
            wp.load_progress(progress_path)))
        w._app_start_ts = time.time() - 1000   # 越过宽限
        # 批次时刻在未来 → tick 只规划落盘、不弹卡（与时间无关的确定性断言）
        wp.batch_times = lambda d, n: [datetime.now() + timedelta(hours=2)] * n
        try:
            w._word_tick()
            prog_now = wp.load_progress(progress_path)
            check("tick_planned", wp.pushed_today(prog_now)
                  and prog_now["batch_done"] == 0 and w._word_bubble is None,
                  (prog_now["batch_done"], w._word_bubble))
        finally:
            wp.batch_times = orig_bt
        # 强制批次时刻为过去 → tick 应推第 1 批
        wp.batch_times = lambda d, n: [datetime.now() - timedelta(minutes=5)] * n
        try:
            w._word_tick()
            bub = w._word_bubble
            check("tick_pushes_batch1", bub is not None and bub.isVisible()
                  and len(bub.words) == wp.BATCH_SIZE,
                  len(bub.words) if bub else None)
            prog_now = wp.load_progress(progress_path)
            check("batch1_progress_saved", prog_now["batch_done"] == 1
                  and prog_now["last_push_ts"] > 0)
            check("bubble_title_batch", "1/" in bub.windowTitle(),
                  bub.windowTitle())
            check("bubble_autoclose_armed", bub._auto_timer.isActive())
            # 气泡卡内容：词/音标/释义齐全
            btexts = norm_text(labels_text(bub))
            for d in bub.words:
                check("bubble_contains_%s" % d["word"],
                      norm_text(d["word"]) in btexts, d["word"])
            bub.reject()
            w._word_bubble = None
            # 最小间隔内再 tick → 不推第 2 批
            w._word_tick()
            check("min_gap_no_batch2", w._word_bubble is None)
        finally:
            wp.batch_times = orig_bt
        # 模态中跳过
        w._word_modal_busy = lambda: True
        wp.batch_times = lambda d, n: [datetime.now() - timedelta(minutes=5)] * n
        try:
            wp.save_progress(progress_path, {
                "date": wp.today_str(), "pushed": True, "words": words[:4],
                "batch_done": 0, "last_push_ts": 0.0})
            w._word_tick()
            check("modal_busy_skips",
                  wp.load_progress(progress_path)["batch_done"] == 0)
        finally:
            wp.batch_times = orig_bt
            del w._word_modal_busy

        # ========== 9) 入睡态被推：唤醒表现 + 弹气泡；关闭后睡回 ==========
        wp.batch_times = lambda d, n: [datetime.now() - timedelta(minutes=5)] * n
        try:
            w.go_sleep()
            drive_until(w, lambda: w.state == "sleep" and not w._sleep_pending)
            check("pre_sleep_for_push", w.state == "sleep", w.state)
            w._word_tick()
            bub2 = w._word_bubble
            check("sleep_push_executed", bub2 is not None and bub2.isVisible())
            check("sleep_wake_look", w.action_name == "wake" or w.state in
                  ("idle", "action"), (w.state, w.action_name))
            bub2.reject()
            check("bubble_close_restores_sleep",
                  w.state == "sleep" and not w._sleep_pending,
                  (w.state, w._sleep_pending))
        finally:
            wp.batch_times = orig_bt

        # ========== 10) 托盘回看：只显示已推批次的词 ==========
        wp.save_progress(progress_path, {
            "date": wp.today_str(), "pushed": True, "words": words[:6],
            "batch_done": 2, "last_push_ts": time.time()})
        said = []
        w.bubble.say = lambda txt, *a, **k: said.append(txt)
        w.open_today_words()
        card2 = w._word_card
        check("tray_review_card_open", card2 is not None
              and card2.windowTitle() == "今日单词")
        check("tray_review_only_pushed",
              card2 is not None and card2.words == words[:4],
              len(card2.words) if card2 else None)
        if card2 is not None:
            card2.reject()
            w._word_card = None
        wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                         "words": []})
        w.open_today_words()
        check("tray_review_empty_bubbles",
              w._word_card is None and len(said) >= 1 and "还没" in said[-1])
        w.bubble.say = lambda txt, *a, **k: None

        # ========== 11) 词库缺失兜底：气泡一次，不崩溃、调度停止 ==========
        said2 = []
        w.bubble.say = lambda txt, *a, **k: said2.append(txt)
        orig_load = wp.load_words
        wp.load_words = lambda *a, **k: []
        try:
            wp.save_progress(progress_path, {"date": "2020-01-01", "pushed": False,
                                             "words": []})
            w._word_tick()
            check("missing_lib_no_crash", len(said2) == 1
                  and "单词库没装上" in said2[0], said2[:1])
            check("missing_lib_stops_schedule", not w.word_timer.isActive())
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
