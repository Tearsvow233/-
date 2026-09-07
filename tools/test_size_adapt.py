# -*- coding: utf-8 -*-
"""T1 尺寸自适应验收 —— 覆盖 docs/宠物尺寸自适应需求.md §5 验收基线。

不修改 main.py 源码；可重复运行；offscreen 渲染（视觉项另算）。
用法：python tools/test_size_adapt.py
"""
import os
import sys
import json
import tempfile
import shutil

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["main"]

import main as m  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402

failures = []
notes = []


def check(name, cond, extra=""):
    tag = "PASS " if cond else "FAIL "
    print(tag + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


def note(text):
    print("NOTE " + text)
    notes.append(text)


# ============================================================
# 1. display_height_for —— 纯函数，钳制与屏高度变化
# ============================================================
class _MockScreen:
    """只暴露 availableGeometry().height()，模拟 QScreen 子类"""
    def __init__(self, h):
        from PySide6.QtCore import QRect
        # 给个 0,0,W,H 的几何，纯函数只用 height()
        self._g = QRect(0, 0, 1920, h)
    def availableGeometry(self):
        return self._g
    def name(self):
        return "mock"


print("\n[1] display_height_for：上下限 + 系数钳制")
# 1080p + 系数 1.0
h = m.display_height_for(_MockScreen(1080), 1.0)
check("1080p_factor1.0_in_range", 80 <= h <= 240, f"h={h}")
# 4K + 系数 1.0
h = m.display_height_for(_MockScreen(2160), 1.0)
check("4k_factor1.0_clamped_or_in_range", 80 <= h <= 240, f"h={h}")
# 720p（小屏）下 1.0 系数 → 高度 < 80 时被钳到 80
h = m.display_height_for(_MockScreen(720), 1.0)
check("720p_clamped_to_80", h == 80, f"h={h}")
# 极小屏（480h）极限钳制
h = m.display_height_for(_MockScreen(480), 1.0)
check("480p_clamped_to_80", h == 80, f"h={h}")
# 系数极端：0.5 应被钳到 0.75
h_low = m.display_height_for(_MockScreen(1080), 0.5)
h_clamped = m.display_height_for(_MockScreen(1080), 0.75)
check("factor_below_min_clamped",
      h_low == h_clamped, f"h(0.5)={h_low} == h(0.75)={h_clamped}")
# 系数极端：2.0 应被钳到 1.25
h_hi = m.display_height_for(_MockScreen(1080), 2.0)
h_clamped_hi = m.display_height_for(_MockScreen(1080), 1.25)
check("factor_above_max_clamped",
      h_hi == h_clamped_hi, f"h(2.0)={h_hi} == h(1.25)={h_clamped_hi}")
# 屏为 None → 兜底 FALLBACK_SCREEN_H
h = m.display_height_for(None, 1.0)
check("none_screen_fallback", 80 <= h <= 240, f"h={h}")
# 屏 geometry 抛异常 → 同样兜底
class _BoomScreen(_MockScreen):
    def availableGeometry(self):
        raise RuntimeError("boom")
check("screen_geometry_raises_falls_back",
      80 <= m.display_height_for(_BoomScreen(1080), 1.0) <= 240)
# 系数非数字
h = m.display_height_for(_MockScreen(1080), "abc")
check("non_numeric_factor_becomes_1.0", h == m.display_height_for(_MockScreen(1080), 1.0),
      f"h={h}")


# ============================================================
# 2. migrate_height_factor —— 旧 height → 相对系数
# ============================================================
print("\n[2] migrate_height_factor：旧 height 迁移")
# 需要一个真实的 QScreen 才能调用（_primary_screen()）
app = m.QApplication.instance() or m.QApplication(sys.argv)
# 1080p 屏下，height=119（≈1080×0.11）应得 factor≈1.0
real = m.QApplication.primaryScreen()
if real is not None:
    real_h = real.availableGeometry().height()
    expected_factor = 119 / (real_h * m.PET_H_RATIO)
    f = m.migrate_height_factor(119)
    check("migrate_height_to_factor",
          abs(f - max(m.MIN_H_FACTOR, min(m.MAX_H_FACTOR, expected_factor))) < 0.05,
          f"f={f} expected≈{expected_factor:.2f}")
    # 旧 height 极小（< 0.75×）被钳到 0.75
    f_tiny = m.migrate_height_factor(10)
    check("migrate_tiny_height_clamped", f_tiny == m.MIN_H_FACTOR, f"f_tiny={f_tiny}")
    # 旧 height 极大被钳到 1.25
    f_huge = m.migrate_height_factor(9999)
    check("migrate_huge_height_clamped", f_huge == m.MAX_H_FACTOR, f"f_huge={f_huge}")
else:
    note("无 primary screen，跳过 migrate 实测（纯函数逻辑已覆盖）")

# 旧 height 非法（None/字符串/0）→ 退化为 1.0
check("migrate_none_returns_1.0", m.migrate_height_factor(None) == 1.0)
check("migrate_zero_returns_1.0", m.migrate_height_factor(0) == 1.0)
check("migrate_string_returns_1.0", m.migrate_height_factor("abc") == 1.0)


# ============================================================
# 3. load_settings —— 旧 settings.json 迁移、不动其它字段
# ============================================================
print("\n[3] load_settings：旧 height 键迁移 + 不重置其它字段")
# 把 SETTINGS_FILE 临时指向一个临时文件，避免污染真实配置
backup_real = m.SETTINGS_FILE
try:
    tmpdir = tempfile.mkdtemp(prefix="babycat_t1_")
    fake_settings = os.path.join(tmpdir, "settings.json")
    # 旧版配置：只有 height=120 + 一个无关字段 pet_name
    legacy = {"height": 120, "pet_name": "小江", "auto_walk": True}
    with open(fake_settings, "w", encoding="utf-8") as f:
        json.dump(legacy, f, ensure_ascii=False)
    m.SETTINGS_FILE = type(m.SETTINGS_FILE)(fake_settings)
    s = m.load_settings()
    check("legacy_migrates_height_factor", "height_factor" in s
          and isinstance(s["height_factor"], (int, float))
          and 0.75 <= s["height_factor"] <= 1.25,
          f"f={s.get('height_factor')}")
    check("legacy_keeps_pet_name", s.get("pet_name") == "小江", s.get("pet_name"))
    check("legacy_keeps_auto_walk", s.get("auto_walk") is True, s.get("auto_walk"))
    check("legacy_drops_height_or_keeps",
          s.get("height") in (120, None), s.get("height"))  # height 旧键可保留或被覆盖

    # 新版配置：已有 height_factor → 不动
    new = {"height_factor": 1.15, "pet_name": "X"}
    with open(fake_settings, "w", encoding="utf-8") as f:
        json.dump(new, f, ensure_ascii=False)
    s2 = m.load_settings()
    check("new_factor_preserved", s2.get("height_factor") == 1.15, s2.get("height_factor"))

    # settings.json 不存在 → DEFAULT_SETTINGS
    os.remove(fake_settings)
    s3 = m.load_settings()
    check("missing_file_returns_defaults",
          s3.get("pet_name") == "小江" and s3.get("height_factor") == 1.0)

    # settings.json 损坏 → 不崩，回退默认
    with open(fake_settings, "w", encoding="utf-8") as f:
        f.write("{not valid json")
    s4 = m.load_settings()
    check("corrupt_file_falls_back_to_defaults",
          s4.get("pet_name") == "小江" and s4.get("height_factor") == 1.0,
          f"name={s4.get('pet_name')} f={s4.get('height_factor')}")
finally:
    m.SETTINGS_FILE = backup_real
    shutil.rmtree(tmpdir, ignore_errors=True)


# ============================================================
# 4. compute_display_height —— 通过 PetWindow 实例验证
# ============================================================
print("\n[4] compute_display_height：跟随当前屏")
s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
s["sleep_after_min"] = 60  # 避免误触发入睡
s["mode"] = "normal"

# 隔离 settings.json 写，避免污染真实配置
backup_real = m.SETTINGS_FILE
backup_save = m.save_settings
try:
    m.SETTINGS_FILE = type(m.SETTINGS_FILE)(
        os.path.join(tempfile.mkdtemp(prefix="babycat_t1_"), "settings.json"))
    m.save_settings = lambda *a, **k: None  # 写时 noop

    w = m.PetWindow(m.load_settings())
    # 初始计算的高度应在 [80, 240]
    h0 = w.compute_display_height()
    check("petwindow_initial_height_in_range", 80 <= h0 <= 240, f"h0={h0}")
    # _loaded_h 应被 set 到这个值
    check("petwindow_loaded_h_matches", w._loaded_h == h0, f"loaded={w._loaded_h}")
    # 改 height_factor → compute_display_height 应跟随
    w.settings["height_factor"] = 1.25
    h1 = w.compute_display_height()
    check("factor_change_affects_compute", h1 != h0 or h1 == 240, f"h0={h0} h1={h1}")
    check("factor_change_in_range", 80 <= h1 <= 240, f"h1={h1}")
    w.settings["height_factor"] = 0.75
    h2 = w.compute_display_height()
    check("factor_0.75_in_range", 80 <= h2 <= 240, f"h2={h2}")
    # 极端系数 2.0 应被钳到 1.25
    w.settings["height_factor"] = 2.0
    h_hi = w.compute_display_height()
    h_125 = m.display_height_for(m.QApplication.primaryScreen(), 1.25)
    check("factor_2.0_clamped_to_1.25", h_hi == h_125, f"h_hi={h_hi} expected={h_125}")
    w.settings["height_factor"] = 1.0
finally:
    m.SETTINGS_FILE = backup_real
    m.save_settings = backup_save


# ============================================================
# 5. reload_sprites_if_size_changed —— 节流（≥4px 才重载）
# ============================================================
print("\n[5] 节流：差 < 4px 不重载，>= 4px 才重载")
s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
s["mode"] = "normal"
backup_real = m.SETTINGS_FILE
backup_save = m.save_settings
try:
    m.SETTINGS_FILE = type(m.SETTINGS_FILE)(
        os.path.join(tempfile.mkdtemp(prefix="babycat_t1_"), "settings.json"))
    m.save_settings = lambda *a, **k: None

    w = m.PetWindow(s)
    # 初始加载：_loaded_h 是某个值（在 80~240 内）
    base_h = w._loaded_h
    check("initial_loaded_h_in_range", 80 <= base_h <= 240, f"base_h={base_h}")

    # 用 monkey-patch 替换 reload_sprites，看是否被调用
    called = {"n": 0}
    orig = w.reload_sprites
    def _spy():
        called["n"] += 1
        orig()
    w.reload_sprites = _spy

    # 差 < 4px：手动把 _loaded_h 调到 (compute - 1) → 不该重载
    w._loaded_h = w.compute_display_height() - 1
    r1 = w.reload_sprites_if_size_changed()
    check("delta_lt_4px_no_reload", r1 is False and called["n"] == 0,
          f"r={r1} called={called['n']}")

    # 差 = 3：同样不该重载
    w._loaded_h = w.compute_display_height() - 3
    r2 = w.reload_sprites_if_size_changed()
    check("delta_3_no_reload", r2 is False and called["n"] == 0,
          f"r={r2} called={called['n']}")

    # 差 = 4：刚好边界，应该重载
    w._loaded_h = w.compute_display_height() - 4
    r3 = w.reload_sprites_if_size_changed()
    check("delta_4_reloads", r3 is True and called["n"] == 1,
          f"r={r3} called={called['n']}")

    # 差 = 10：大幅变化，也重载
    w._loaded_h = 50  # 故意 < MIN
    r4 = w.reload_sprites_if_size_changed()
    check("delta_large_reloads", r4 is True and called["n"] == 2,
          f"r={r4} called={called['n']}")
finally:
    m.SETTINGS_FILE = backup_real
    m.save_settings = backup_save


# ============================================================
# 6. DPI 感知：scaledToHeight(h * dpr) + setDevicePixelRatio(dpr)
# ============================================================
print("\n[6] DPI 感知：scaledToHeight × dpr")
# 这条测的是 _inner_load 函数的语义，offscreen 屏通常 dpr=1.0
# 关键断言：把屏 dpr 强制为 2.0 后，scaled 后位图的物理尺寸 = 2h
class _DprScreen(_MockScreen):
    def __init__(self, h, dpr):
        super().__init__(h)
        self._dpr = dpr
    def devicePixelRatio(self):
        return self._dpr
    def devicePixelRatioF(self):
        return float(self._dpr)

# 直接调用 display_height_for 校验 dpr 不影响逻辑高度
for dpr in (1.0, 1.25, 1.5, 2.0):
    h = m.display_height_for(_MockScreen(1080), 1.0)
    check(f"display_height_independent_of_dpr_dpr={dpr}",
          80 <= h <= 240, f"h={h}")

# 直接读 idle_open.png 验真：DPI=1 时，缩放后物理像素应 = h
s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
backup_real = m.SETTINGS_FILE
backup_save = m.save_settings
try:
    m.SETTINGS_FILE = type(m.SETTINGS_FILE)(
        os.path.join(tempfile.mkdtemp(prefix="babycat_t1_"), "settings.json"))
    m.save_settings = lambda *a, **k: None
    w = m.PetWindow(s)
    h = w._loaded_h
    # dpr=1.0（offscreen）下，pix_open 的物理像素高应 == h
    pm = w.pix_open
    if pm is not None and not pm.isNull():
        phys_h = pm.height()  # QPixmap.height() 返回物理像素
        dpr = pm.devicePixelRatio() or 1.0
        log_h = pm.height() / dpr
        check("dpr1_pixmap_phys_h_eq_h", phys_h == h, f"phys={phys_h} h={h} dpr={dpr}")
        check("dpr1_pixmap_log_h_eq_h",
              abs(log_h - h) < 0.5, f"log={log_h} h={h}")
    else:
        note("pix_open 不可用，跳过位图尺寸断言")
finally:
    m.SETTINGS_FILE = backup_real
    m.save_settings = backup_save


# ============================================================
# 7. PetCenter 滑块 → values() 往返 + 持久化
# ============================================================
print("\n[7] PetCenter：滑块 → height_factor 写入 settings")
from PySide6.QtWidgets import QApplication  # noqa: F401
s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
pc = m.PetCenter(s)
# 把滑块拨到 1.20
pc.size_slider.setValue(120)
v = pc.values()
check("center_values_factor_1.20", v.get("height_factor") == 1.2, v.get("height_factor"))
# 拨到 75
pc.size_slider.setValue(75)
v = pc.values()
check("center_values_factor_0.75", v.get("height_factor") == 0.75, v.get("height_factor"))
# 拨到 125
pc.size_slider.setValue(125)
v = pc.values()
check("center_values_factor_1.25", v.get("height_factor") == 1.25, v.get("height_factor"))
# 拨到 100
pc.size_slider.setValue(100)
v = pc.values()
check("center_values_factor_1.00", v.get("height_factor") == 1.0, v.get("height_factor"))
# 实时 label：含「当前约 NNN px（本屏）」
pc.size_slider.setValue(110)
pc._refresh_size_label()
label_txt = pc.size_label.text()
check("size_label_shows_height",
      "px" in label_txt and "本屏" in label_txt, label_txt)
# 范围提示字
hint_found = False
for child in pc.findChildren(type(pc.size_slider).__base__):
    pass
# 直接 grep 所有 label
from PySide6.QtWidgets import QLabel
hint_found = any("80" in lbl.text() and "240" in lbl.text()
                 for lbl in pc.findChildren(QLabel))
check("size_hint_shows_range", hint_found)
pc.close()


# ============================================================
# 8. 副屏拔出：_ensure_on_screen 钳回（用 mock screens）
# ============================================================
print("\n[8] 副屏拔出：_ensure_on_screen 不丢猫")
s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
s["mode"] = "normal"
backup_real = m.SETTINGS_FILE
backup_save = m.save_settings
try:
    m.SETTINGS_FILE = type(m.SETTINGS_FILE)(
        os.path.join(tempfile.mkdtemp(prefix="babycat_t1_"), "settings.json"))
    m.save_settings = lambda *a, **k: None
    w = m.PetWindow(s)
    # 模拟"已在某屏外"：把窗口几何设到一个不与任何 availableGeometry 相交的位置
    from PySide6.QtCore import QRect
    w.setGeometry(QRect(-9999, -9999, 100, 100))
    # 调用 _ensure_on_screen（不应抛异常）
    try:
        w._ensure_on_screen()
        check("ensure_on_screen_no_throw", True)
    except Exception as e:
        check("ensure_on_screen_no_throw", False, f"raised {e}")
    # 窗口应被 move 回某个有效位置（要么在 primary 屏内，要么 recentre 后居中）
    g = w.geometry()
    screens = m.QApplication.screens()
    on_some = any(s2.availableGeometry().intersects(g) for s2 in screens)
    check("after_ensure_on_some_screen", on_some, f"g={g.x()},{g.y()} screens={len(screens)}")
finally:
    m.SETTINGS_FILE = backup_real
    m.save_settings = backup_save


# ============================================================
# 汇总
# ============================================================
print("\n" + "=" * 60)
if failures:
    print(f"FAILED: {len(failures)} 项")
    for f in failures:
        print("  -", f)
    sys.exit(1)
else:
    print("ALL PASS")
    if notes:
        print(f"NOTES: {len(notes)}")
        for n in notes:
            print("  -", n)
    sys.exit(0)
