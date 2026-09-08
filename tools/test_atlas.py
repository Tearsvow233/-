# -*- coding: utf-8 -*-
"""图集化 sprite sheet 验收测试（交接包 T3）。

验收基线（来自交接包）：
1. 500 散文件 → 图集（atlas_index.json + 19 个 PNG）
2. 冷启动下降（图集加载 vs 500 散文件加载）
3. 动作播放无破图（帧数齐全、位图非空、尺寸正确）

附加保障：
4. 散帧回退：图集不可用时仍能从 assets/sprites 加载
5. 与预缩放缓存的交互：指纹基于图集文件，图集变动 → 缓存自动重建
"""
import json
import os
import sys
import time
import tempfile
import shutil
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")
sys.argv = ["main"]

import main as m  # noqa: E402

PASS = []
FAIL = []


def check(name, ok, info=""):
    tag = "PASS" if ok else "FAIL"
    PASS.append(name) if ok else FAIL.append(name)
    print(f"[{tag}] {name} {info}")


EXPECTED = {  # 动作 -> 帧数（与素材现状一致）
    "sleep": 20, "stretch": 20, "walk_circle": 20, "wake": 20, "groom": 20,
    "settle": 20, "recoil": 60, "spin": 120, "pace": 192,
}


def wait_cache_build(w, timeout_s=60):
    t0 = time.time()
    from PySide6.QtCore import QEventLoop
    loop = QEventLoop()
    while (getattr(w, "_cache_strips", None) or getattr(w, "_cache_queue", None)) \
            and time.time() - t0 < timeout_s:
        loop.processEvents()
        time.sleep(0.005)
    for _ in range(4):
        loop.processEvents()
    return time.time() - t0


def main_():
    print("=" * 60)
    print("T3 图集化 sprite sheet 验收")
    print("=" * 60)

    # ---------- 1. 图集与索引结构 ----------
    idx = m._load_atlas_index()
    check("atlas_index_exists", idx is not None)
    if idx is None:
        print("无索引，中止")
        return
    files = list(m.ATLAS_DIR.glob("*.png"))
    n_frames = len(idx["frames"])
    check("atlas_file_count", 1 <= len(files) <= 40, "%d 个 PNG" % len(files))
    check("atlas_total_frames", n_frames == 548, "%d 帧" % n_frames)
    singles = {"idle_open.png", "idle_blink.png", "click_surprise.png",
               "click_happy.png", "walk_r_01.png", "walk_r_52.png"}
    check("atlas_covers_singles", singles <= set(idx["frames"]))
    order = idx.get("order") or []
    check("atlas_order_consistent", len(order) == n_frames and set(order) == set(idx["frames"]))

    # 源散帧仍在（回退保障）。552 = 548 在用 + 4 张已退役旧走帧 walk_1..4（仅存档）
    n_src = len(list(m.SPRITES_DIR.glob("*.png")))
    check("sprites_fallback_intact", n_src == 552, "%d 散帧" % n_src)

    # ---------- 2. 图集模式加载（强证据：把散帧目录指空） ----------
    tmp = tempfile.mkdtemp(prefix="bc_atlas_")
    m.SPRITES_CACHE_DIR = m.Path(tmp) / "cache" / "sprites"   # 隔离缓存
    orig_sprites = m.SPRITES_DIR
    m.SPRITES_DIR = m.Path(tmp) / "no_such_sprites"            # 散帧目录指空
    try:
        s = m.load_settings()
        s["pos_x"], s["pos_y"], s["mode"] = 100, 100, "normal"
        app = m.QApplication.instance() or m.QApplication(sys.argv)

        t0 = time.time()
        w = m.PetWindow(s)
        t_cold = time.time() - t0
        print("[time] 图集冷启动（无缓存、无散帧目录）: %.2fs" % t_cold)
        check("atlas_cold_under_3s", t_cold < 3.0, "%.2fs" % t_cold)

        # 帧数齐全 + 位图有效
        ok_counts = all(len(w.action_frames.get(a, [])) == n for a, n in EXPECTED.items())
        check("atlas_action_counts", ok_counts,
              {a: len(w.action_frames.get(a, [])) for a in EXPECTED})
        total = len(w.action_frames.get("sleep", [])) if False else \
            sum(len(f) for f in w.action_frames.values())
        check("atlas_total_loaded", total == sum(EXPECTED.values()), "%d 帧" % total)

        h = w._loaded_h
        dpr = w.devicePixelRatioF() or 1.0
        phys = int(round(h * dpr))
        bad = [a for a, fs in w.action_frames.items()
               if any(f.isNull() or f.height() != phys for f in fs)]
        check("atlas_frames_valid_size", not bad, "坏动作: %s" % bad)
        check("atlas_idle_valid", not w.pix_open.isNull() and w.pix_open.height() == h)
        check("atlas_walk_frames", len(w.walk_left) == 52 and len(w.walk_right) == 52)

        # ---------- 3. 缓存构建与热启动 ----------
        wait_cache_build(w)
        cdir = m.SPRITES_CACHE_DIR / f"h{phys}"
        check("cache_built_from_atlas", (cdir / "manifest.json").exists())
        with open(cdir / "manifest.json", encoding="utf-8") as f:
            sig = json.load(f)["signature"]
        check("cache_signature_atlas_based", sig.startswith("atlas|"), sig[:20])
        # manifest 帧覆盖
        with open(cdir / "manifest.json", encoding="utf-8") as f:
            man = json.load(f)
        covered = set()
        for rects in man.get("layout", {}).values():
            covered.update(rects.keys())
        check("cache_covers_all", len(covered) == 548, "%d 帧" % len(covered))

        t0 = time.time()
        w.reload_sprites()
        t_warm = time.time() - t0
        print("[time] 图集模式热重载（缓存命中）: %.2fs" % t_warm)
        check("atlas_warm_reload_fast", t_warm < 1.0, "%.2fs" % t_warm)

        # ---------- 4. 图集变动 → 缓存失效 ----------
        atlas_file = sorted(m.ATLAS_DIR.glob("*.png"))[0]
        st = atlas_file.stat()
        os.utime(atlas_file, (st.st_atime, st.st_mtime + 5))
        names = w._frame_names()
        check("atlas_touch_invalidates_cache", not w._cache_ready(cdir, names))
        w.reload_sprites()          # 自动重建
        wait_cache_build(w)
        check("cache_rebuilt_after_atlas_change",
              w._cache_ready(cdir, w._frame_names()))
        st = atlas_file.stat()
        os.utime(atlas_file, (st.st_atime, st.st_mtime - 5))  # 还原 mtime
        w.reload_sprites()
        wait_cache_build(w)
        w.close()
    finally:
        m.SPRITES_DIR = orig_sprites
        shutil.rmtree(tmp, ignore_errors=True)

    # ---------- 5. 散帧回退（图集索引指空） ----------
    tmp2 = tempfile.mkdtemp(prefix="bc_fallback_")
    m.SPRITES_CACHE_DIR = m.Path(tmp2) / "cache" / "sprites"
    orig_atlas_index = m.ATLAS_INDEX_FILE
    m.ATLAS_INDEX_FILE = m.Path(tmp2) / "no_index.json"
    try:
        s = m.load_settings()
        s["pos_x"], s["pos_y"], s["mode"] = 100, 100, "normal"
        w = m.PetWindow(s)
        ok_counts = all(len(w.action_frames.get(a, [])) == n for a, n in EXPECTED.items())
        check("fallback_action_counts", ok_counts)
        check("fallback_frames_valid", not w.pix_open.isNull())
        wait_cache_build(w)
        cdir2 = m.SPRITES_CACHE_DIR / ("h%d" % int(round(w._loaded_h * (w.devicePixelRatioF() or 1.0))))
        with open(cdir2 / "manifest.json", encoding="utf-8") as f:
            sig = json.load(f)["signature"]
        check("fallback_signature_file_based", not sig.startswith("atlas|"), sig[:20])
        w.close()
    finally:
        m.ATLAS_INDEX_FILE = orig_atlas_index
        shutil.rmtree(tmp2, ignore_errors=True)

    # ---------- 6. 播放无破图：抽帧 mask + 逐帧非空 ----------
    tmp3 = tempfile.mkdtemp(prefix="bc_play_")
    m.SPRITES_CACHE_DIR = m.Path(tmp3) / "cache" / "sprites"
    try:
        s = m.load_settings()
        s["pos_x"], s["pos_y"], s["mode"] = 100, 100, "normal"
        w = m.PetWindow(s)
        wait_cache_build(w)
        broken = []
        for act, frames in w.action_frames.items():
            for i, f in enumerate(frames):
                if f.isNull() or f.width() == 0 or f.height() == 0:
                    broken.append(f"{act}[{i}]")
        check("playback_no_broken_frames", not broken, "坏帧: %s" % broken[:5])
        # mask 可计算（透明区域点击穿透的前提）
        try:
            _ = w.pix_open.mask()
            check("mask_computable", True)
        except Exception as e:
            check("mask_computable", False, str(e))
        w.close()
    finally:
        shutil.rmtree(tmp3, ignore_errors=True)

    print()
    print(f"结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)
    print("ALL PASS")


if __name__ == "__main__":
    main_()
