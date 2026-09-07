# -*- coding: utf-8 -*-
"""探测 PetCenter 弹窗的尺寸来源：谁把窗口撑宽、是否超屏幕、是否有横向滚动"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QLineEdit, QPushButton, QCheckBox, QComboBox
from main import PetCenter, DIALOG_QSS

app = QApplication(sys.argv)
app.setStyleSheet(DIALOG_QSS)
try:
    app.styleHints().setColorScheme(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ColorScheme.Dark)
except Exception:
    pass

screen = app.primaryScreen()
avail = screen.availableGeometry()
print(f"SCREEN_AVAIL  {avail.width()}x{avail.height()}  @({avail.x()},{avail.y()})")
print(f"DEVICE_PIXEL_RATIO {screen.devicePixelRatio():.2f}")

dummy = {
    "pet_name": "小江", "height": 100, "auto_walk": True,
    "ai_enabled": True,
    "ai_api_key": "待填",
    "ai_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "ai_model": "glm-4-flash-250414",
    "personality": "粘人", "sleep_after_min": 5,
    "action_min_sec": 10, "action_max_sec": 30,
    "walk_min_sec": 12, "walk_max_sec": 30,
    "chat_min_sec": 40, "chat_max_sec": 90,
    "blink_min_sec": 3, "blink_max_sec": 7,
    "reminders": [
        {"name": "下课", "mode": "interval", "interval_min": 45, "once": True, "enabled": True},
        {"name": "喝水", "mode": "interval", "interval_min": 40, "once": False, "enabled": True},
        {"name": "起来活动一下", "mode": "interval", "interval_min": 30, "once": False, "enabled": True},
    ],
}

dlg = PetCenter(dummy)
dlg.show()
app.processEvents()
app.processEvents()

print(f"DLG  sizeHint        {dlg.sizeHint().width()}x{dlg.sizeHint().height()}")
print(f"DLG  minimumSizeHint {dlg.minimumSizeHint().width()}x{dlg.minimumSizeHint().height()}")
print(f"DLG  actual size     {dlg.width()}x{dlg.height()}  minW={dlg.minimumWidth()} maxW={dlg.maximumWidth()}")

scroll = dlg.findChild(QScrollArea)
vp = scroll.viewport()
container = scroll.widget()
print(f"SCROLL viewport      {vp.width()}x{vp.height()}")
print(f"CONT  minimumSizeHint {container.minimumSizeHint().width()}x{container.minimumSizeHint().height()}")
print(f"CONT  sizeHint        {container.sizeHint().width()}x{container.sizeHint().height()}")
hb = scroll.horizontalScrollBar()
print(f"HSCROLL range 0..{hb.maximum()}  (>0 说明内容比可视区宽 → 需横向拖动)")

# 找出最宽的标签/控件（单行文本像素宽）
fm = dlg.fontMetrics()
rows = []
def walk(w, depth=0):
    for c in w.findChildren(type(w).__bases__[0]) if False else w.children():
        pass
def collect(w):
    for child in w.findChildren(object):
        if isinstance(child, QLabel):
            t = child.text().replace("\n", " ")
            rows.append((fm.horizontalAdvance(t), "QLabel", t[:60]))
        elif isinstance(child, QPushButton):
            t = child.text()
            rows.append((fm.horizontalAdvance(t), "QPushButton", t[:60]))
        elif isinstance(child, QLineEdit):
            ph = child.placeholderText()
            rows.append((fm.horizontalAdvance(ph or child.text()), "QLineEdit", (ph or child.text())[:60]))
collect(container)
rows.sort(reverse=True)
print("--- TOP 8 最宽内容（单行像素宽，>viewport 宽度即为撑宽元凶）---")
for px, kind, t in rows[:8]:
    mark = "  <-- 超视口" if px > vp.width() else ""
    print(f"  {px:5d}px  {kind:<10s} {t}{mark}")

out = Path(__file__).parent.parent / "assets/_probe"
out.mkdir(parents=True, exist_ok=True)
dlg.grab().save(str(out / "center_size_probe.png"))
print("saved", out / "center_size_probe.png")
app.quit()
