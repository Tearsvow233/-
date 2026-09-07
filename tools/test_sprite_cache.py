# -*- coding: utf-8 -*-
"""T3 预缩放缓存验收:
1. 冷启动(无缓存)计时 → 后台构建缓存
2. 热启动(命中缓存)计时 → 应显著快于冷启动
3. 缓存内容完整(manifest + 全部帧)
4. 位图正确性(物理高度、DPR、逻辑尺寸)
5. 指纹失效(源素材变化 → 缓存不命中)
6. 旧高度目录清理

用法:python tools/test_sprite_cache.py
"""
import os
import sys
import json
import time
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m  # noqa: E402
from PySide6.QtCore import QEventLoop  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


def wait_cache_build(w, timeout_s=60):
    """驱动事件循环直到缓存写完(后台 QTimer 分批拼 strip 写盘)"""
    t0 = time.time()
    loop = QEventLoop()
    while w._cache_strips and time.time() - t0 < timeout_s:
        loop.processEvents()
        time.sleep(0.005)
    loop.processEvents()
    # 再多跑两拍让收尾(manifest/prune)执行完
    for _ in range(4):
        loop.processEvents()
        time.sleep(0.01)
    return time.time() - t0


def main_test():
    # 用独立临时缓存目录,不碰真实 cache/
    tmp = tempfile.mkdtemp(prefix="babycat_cache_test_")
    m.SPRITES_CACHE_DIR = m.Path(tmp) / "sprites"
    try:
        s = m.load_settings()
        s["pos_x"] = 100
        s["pos_y"] = 100
        s["mode"] = "normal"
        app = m.QApplication.instance() or m.QApplication(sys.argv)

        # ---------- 1. 冷启动(无缓存) ----------
        w = m.PetWindow(s)
        h = w._loaded_h
        phys = int(round(h * (w.devicePixelRatioF() or 1.0)))
        cdir = m.SPRITES_CACHE_DIR / f"h{phys}"
        check("cold_no_cache_dir", not cdir.exists(), cdir)
        t0 = time.time()
        w.reload_sprites()
        t_cold = time.time() - t0
        build_s = wait_cache_build(w)
        print("[time] 冷重载 %.2fs + 后台构建缓存 %.2fs" % (t_cold, build_s))

        # ---------- 2. 缓存内容完整(strip + manifest) ----------
        names = w._frame_names()
        strip_files = list(cdir.glob("strip_*.png"))
        check("cache_strip_files", len(strip_files) >= 5,
              "%d 个 strip 文件" % len(strip_files))
        manifest = cdir / "manifest.json"
        check("manifest_exists", manifest.exists())
        if manifest.exists():
            with open(manifest, encoding="utf-8") as f:
                man = json.load(f)
            covered = set()
            for sf, rects in man.get("layout", {}).items():
                check(f"strip_file_exists_{sf}", (cdir / sf).exists())
                covered.update(rects.keys())
            check("manifest_covers_all_frames", set(names) <= covered,
                  "%d/%d" % (len(set(names) & covered), len(names)))
            check("manifest_signature_matches",
                  man.get("signature") == w._cache_signature(names))

        # ---------- 3. 热启动(命中缓存) ----------
        check("cache_ready_now", w._cache_ready(cdir, names))
        t0 = time.time()
        w.reload_sprites()
        t_warm = time.time() - t0
        print("[time] 热重载 %.2fs(冷 %.2fs,加速 %.1fx)"
              % (t_warm, t_cold, t_cold / t_warm if t_warm else 0))
        check("warm_much_faster", t_warm < t_cold * 0.5,
              "warm=%.2fs cold=%.2fs" % (t_warm, t_cold))
        check("warm_under_1s", t_warm < 1.0, "%.3fs" % t_warm)

        # ---------- 4. 位图正确性 ----------
        pm = w.pix_open
        check("bitmap_logical_h", abs(pm.height() - h) <= 1,
              "logical=%d expect=%d" % (pm.height(), h))
        check("bitmap_dpr_set", abs(pm.devicePixelRatio() - (w.devicePixelRatioF() or 1.0)) < 0.01,
              "dpr=%s" % pm.devicePixelRatio())
        check("bitmap_phys_h", pm.height() * pm.devicePixelRatio() == phys,
              "phys=%d expect=%d" % (pm.height() * pm.devicePixelRatio(), phys))
        for k, frames in w.action_frames.items():
            if frames:
                check(f"bitmap_{k}_frame0", abs(frames[0].height() - h) <= 1,
                      frames[0].height())
                break

        # ---------- 5. 指纹失效:源素材变化 → 不命中 ----------
        with open(manifest, encoding="utf-8") as f:
            mdata = json.load(f)
        mdata["signature"] = mdata["signature"][:-5] + "XXXXX"
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump(mdata, f)
        check("tampered_manifest_invalid", not w._cache_ready(cdir, names))
        # 恢复指纹
        with open(manifest, "w", encoding="utf-8") as f:
            json.dump({"signature": w._cache_signature(names),
                       "layout": mdata["layout"]}, f)
        check("restored_manifest_valid", w._cache_ready(cdir, names))

        # 缺一个 strip 文件 → 不命中
        victim = cdir / list(mdata["layout"].keys())[0]
        victim.rename(victim.with_suffix(".bak"))
        check("missing_strip_invalid", not w._cache_ready(cdir, names))
        victim.with_suffix(".bak").rename(victim)
        check("restored_strip_valid", w._cache_ready(cdir, names))

        # ---------- 6. 旧高度目录清理 ----------
        old_dir = m.SPRITES_CACHE_DIR / "h999"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "dummy.png").write_bytes(b"\x89PNG")
        w._prune_old_cache(cdir)
        check("old_height_pruned", not old_dir.exists())
        check("keep_dir_alive", cdir.exists())

        # ---------- 7. 二次构造 PetWindow(整窗热启动) ----------
        w.close()
        t0 = time.time()
        w2 = m.PetWindow(s)
        t_full = time.time() - t0
        print("[time] 热启动整窗构造 %.2fs" % t_full)
        check("warm_window_under_1s", t_full < 1.0, "%.2fs" % t_full)
        check("warm_window_no_pending_build", not w2._cache_strips
              and not w2._cache_timer.isActive())
        w2.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("=" * 60)
    if failures:
        print("FAILED:", failures)
        sys.exit(1)
    print("CACHE TEST RESULT: ALL PASS")


if __name__ == "__main__":
    main_test()
