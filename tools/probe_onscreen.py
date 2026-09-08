#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探针3：真实屏幕上复现帧显示（透明窗 + setMask），ImageGrab 抓屏对拍。

用法: .venv/Scripts/python.exe tools/probe_onscreen.py [no-mask]
"""
import os
import sys
import time
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "output" / "probe_onscreen"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QPixmap, QTransform, QImageReader, QGuiApplication
from PySide6.QtCore import Qt

NO_MASK = "no-mask" in sys.argv

app = QApplication(sys.argv)
screen = QGuiApplication.primaryScreen()
DPR = screen.devicePixelRatio()
H = 100
phys = int(round(H * DPR))
print(f"screen DPR={DPR} phys={phys}")

idx = json.load(open(ROOT / "assets/atlases/atlas_index.json", encoding="utf-8"))

def atlas_frame(name):
    fname, x, y, w, hh = idx["frames"][name]
    r = QImageReader(str(ROOT / "assets" / "atlases" / fname))
    img = r.read()
    big = QPixmap.fromImage(img)
    pm = big.copy(x, y, w, hh).scaledToHeight(phys, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(pm)
    out.setDevicePixelRatio(DPR)
    return out

win = QLabel()
win.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

def mir_qimage(pm):
    """main.py 同款修复：QImage 层镜像，mask() 正常"""
    img = pm.toImage().transformed(QTransform().scale(-1, 1))
    out = QPixmap.fromImage(img)
    out.setDevicePixelRatio(pm.devicePixelRatioF())
    return out

frames = {
    "idle_open": atlas_frame("idle_open.png"),
    "pace_92": atlas_frame("pace_92.png"),
    "pace_92_mir": mir_qimage(atlas_frame("pace_92.png")),
    "pace_01_mir": mir_qimage(atlas_frame("pace_01.png")),
}

have_mss = False
from PIL import ImageGrab

win.move(400, 300)
win.show()

for name, pm in frames.items():
    win.setPixmap(pm)
    win.adjustSize()
    if not NO_MASK:
        m = pm.mask()
        if m is not None:
            win.setMask(m)
    win.show()
    app.processEvents()
    time.sleep(0.6)
    app.processEvents()
    geo = win.geometry()
    # 抓屏（物理像素）
    x0, y0 = int(geo.x()*DPR), int(geo.y()*DPR)
    im = ImageGrab.grab(bbox=(x0, y0, x0+int(geo.width()*DPR), y0+int(geo.height()*DPR)))
    tag = "nomask_" if NO_MASK else ""
    im.save(OUT / f"{tag}{name}.png")
    # 同时存期望值（pixmap 位图本身）
    pm.toImage().save(str(OUT / f"expect_{name}.png"))
    print(f"抓屏 {name}: win={geo.width()}x{geo.height()}@{geo.x()},{geo.y()} -> {im.size}")

win.close()
print("完成，输出在 output/probe_onscreen/")
