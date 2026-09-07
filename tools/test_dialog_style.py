# -*- coding: utf-8 -*-
"""测试暗色玻璃主题在 PetCenter 上的实际渲染效果"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from main import DIALOG_QSS, PetCenter, BASE_DIR

app = QApplication(sys.argv)
app.setStyleSheet(DIALOG_QSS)
try:
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
except Exception:
    pass

icon_path = BASE_DIR / "assets" / "icon.ico"
if icon_path.exists():
    app.setWindowIcon(__import__("PySide6.QtGui", fromlist=["QIcon"]).QIcon(str(icon_path)))

dummy_settings = {
    "pet_name": "小江",
    "height": 100,
    "auto_walk": True,
    "water_min": 45,
    "sit_min": 60,
    "ai_enabled": True,
    "ai_api_key": "待填",
    "ai_base_url": "https://open.bigmodel.cn/api/paas/v4",
    "ai_model": "glm-4-flash-250414",
    "reminders": [
        {"name": "下课", "interval_min": 45, "enabled": True},
        {"name": "喝水", "mode": "daily", "at": "09:00", "enabled": True},
        {"name": "开会", "mode": "weekly", "weekday": 1, "at": "20:00", "enabled": True},
    ],
}

dlg = PetCenter(dummy_settings)
dlg.show()
# 等待布局完成
from PySide6.QtCore import QTimer

def save_previews():
    root = Path(__file__).parent.parent / "assets/_preview2"
    # 客户区截图
    dlg.grab().save(str(root / "dialog_style_preview.png"))
    # 完整窗口截图（含标题栏、图标）
    screen = QApplication.primaryScreen()
    full = screen.grabWindow(dlg.winId())
    full.save(str(root / "dialog_window_preview.png"))

QTimer.singleShot(400, save_previews)
QTimer.singleShot(700, app.quit)
app.exec()
print("saved dialog_style_preview.png + dialog_window_preview.png")
