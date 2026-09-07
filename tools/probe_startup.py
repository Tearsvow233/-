# -*- coding: utf-8 -*-
"""T3 启动耗时探针:测 PetWindow 构造 + 后台缓存构建耗时。
用法:python tools/probe_startup.py
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
from PySide6.QtCore import QEventLoop  # noqa: E402

s = m.load_settings()
s["pos_x"] = 100
s["pos_y"] = 100
s["mode"] = "normal"
app = m.QApplication.instance() or m.QApplication(sys.argv)

t0 = time.time()
w = m.PetWindow(s)
t_init = time.time() - t0

loop = QEventLoop()
t0 = time.time()
while w._cache_strips:
    loop.processEvents()
    time.sleep(0.005)
build = time.time() - t0
for _ in range(4):
    loop.processEvents()

n = sum(len(f) for f in w.action_frames.values()) + 10
w.close()
print("PetWindow构造 %.2fs | 后台缓存构建 %.2fs | 加载帧数 %d | 缓存目录 %s"
      % (t_init, build, n, m.SPRITES_CACHE_DIR))
