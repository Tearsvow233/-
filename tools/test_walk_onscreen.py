#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""端到端验证：真实 PetWindow 散步序列上屏抓图（镜像轮 + 非镜像轮关键帧）。
抓图存 output/test_walk_onscreen/，人工或脚本检查猫是否完整。

用法: .venv/Scripts/python.exe tools/test_walk_onscreen.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "output" / "test_walk_onscreen"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QGuiApplication
from PIL import ImageGrab

import main as m

app = QApplication(sys.argv)
settings = m.load_settings()
pet = m.PetWindow(settings)
pet.show()
app.processEvents()
time.sleep(0.8)
DPR = QGuiApplication.primaryScreen().devicePixelRatio()
print("DPR", DPR, "walk_seq", len(pet.walk_seq))


def grab(tag):
    g = pet.geometry()
    x0, y0 = int(g.x() * DPR), int(g.y() * DPR)
    im = ImageGrab.grab(bbox=(x0, y0, x0 + int(g.width() * DPR), y0 + int(g.height() * DPR)))
    im.save(OUT / f"{tag}.png")
    print("grabbed", tag, im.size, "at", g.x(), g.y())


pet.move(500, 350)
app.processEvents()
time.sleep(0.3)

# 镜像轮关键帧（含用户截图同款 k=91：镜像后的左向坐姿）
for k in (0, 50, 91, 150, 192, 212):
    pet.state = "walk"
    pet._walk_mir = True
    pet.walk_dir = -1
    pet.walk_frame = k
    pet.walk_step()
    app.processEvents()
    time.sleep(0.35)
    app.processEvents()
    grab(f"mir_{k:03d}")

# 非镜像轮关键帧（尾部为镜像收尾帧）
for k in (0, 91, 192, 200, 212):
    pet.state = "walk"
    pet._walk_mir = False
    pet.walk_dir = 1
    pet.walk_frame = k
    pet.walk_step()
    app.processEvents()
    time.sleep(0.35)
    app.processEvents()
    grab(f"seq_{k:03d}")

# idle 对照
pet.state = "idle"
pet.set_frame(pet.pix_open)
app.processEvents()
time.sleep(0.35)
grab("idle")

pet.close()
print("done ->", OUT)
