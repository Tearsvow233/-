#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探针6：遮罩修复方案验证。
F: E内容 + QBitmap.fromImage(E.mask().toImage())  （mask 过一遍 QImage 消毒）
G: E内容 + QBitmap.fromImage(E.toImage() 黑底合成)（绕开 mask() 直接从 alpha 建）
H: A内容 + 同 F 方案（确认对正常内容不回归）
用法: .venv/Scripts/python.exe tools/probe_mask_fix.py
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "probe_fix"
OUT.mkdir(parents=True, exist_ok=True)

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtGui import QPixmap, QGuiApplication, QBitmap, QImage, QPainter
from PySide6.QtCore import Qt
from PIL import ImageGrab

app = QApplication(sys.argv)
DPR = QGuiApplication.primaryScreen().devicePixelRatio()
phys = int(round(100 * DPR))


def load_pm(path):
    p = QPixmap(str(path)).scaledToHeight(phys, Qt.TransformationMode.SmoothTransformation)
    p.setDevicePixelRatio(DPR)
    return p

FLIP = OUT / "_pace92_flip.png"
if not FLIP.exists():
    from PIL import Image
    Image.open(ROOT / "assets" / "sprites" / "pace_92.png").transpose(
        Image.FLIP_LEFT_RIGHT).save(FLIP)

A = load_pm(ROOT / "assets" / "sprites" / "pace_92.png")
E = load_pm(FLIP)


def mask_sanitized(pm):
    """pm.mask() 的位图过 QImage 消毒一遍，重建干净 QBitmap"""
    return QBitmap.fromImage(pm.mask().toImage())


def mask_from_alpha(pm):
    """绕开 mask()：alpha>0 合成黑底→灰度→阈值成位图"""
    img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    flat = QImage(img.size(), QImage.Format.Format_ARGB32)
    flat.fill(Qt.GlobalColor.black)
    qp = QPainter(flat)
    qp.drawImage(0, 0, img)
    qp.end()
    gray = flat.convertToFormat(QImage.Format.Format_Grayscale8)
    mono = gray.createMaskFromColor(0, Qt.MaskMode.MaskOutColor)  # 非纯黑→1
    return QBitmap.fromImage(mono)


cases = [
    ("F_E_sanitized", E, mask_sanitized(E)),
    ("G_E_fromalpha", E, mask_from_alpha(E)),
    ("H_A_sanitized", A, mask_sanitized(A)),
    ("I_A_fromalpha", A, mask_from_alpha(A)),
]

bg = QLabel()
bg.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
bg.setStyleSheet("background-color: #2b5876;")
bg.resize(760, 200)
bg.move(150, 250)
bg.show()

wins = []
for i, (tag, pm, m) in enumerate(cases):
    w = QLabel(bg)
    w.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    w.setPixmap(pm)
    w.adjustSize()
    w.setMask(m)
    w.move(20 + i * 180, 30)
    w.show()
    wins.append((tag, w))

app.processEvents()
time.sleep(1.0)
app.processEvents()

g = bg.geometry()
x0, y0 = int(g.x() * DPR), int(g.y() * DPR)
shot = ImageGrab.grab(bbox=(x0, y0, x0 + int(g.width() * DPR), y0 + int(g.height() * DPR)))
shot.save(OUT / "_full.png")
for i, (tag, _) in enumerate(wins):
    cx, cy = int((20 + i * 180) * DPR), int(30 * DPR)
    shot.crop((cx, cy, cx + phys, cy + phys)).save(OUT / f"{tag}.png")
    print("grabbed", tag)
for _, w in wins:
    w.close()
bg.close()
print("done")
