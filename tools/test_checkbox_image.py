# -*- coding: utf-8 -*-
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QCheckBox
from PySide6.QtCore import Qt, QTimer

app = QApplication(sys.argv)

w = QWidget()
layout = QVBoxLayout(w)
cb = QCheckBox("测试")
cb.setChecked(True)
layout.addWidget(cb)

# 尝试多种 url 写法
url = (Path(__file__).parent.parent / "assets" / "check.png").as_uri()
qss = f"""
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border-radius: 4px;
    border: 1px solid #4A4A58;
    background: #1C1C24;
}}
QCheckBox::indicator:checked {{
    background: #3DD6B0;
    border: 1px solid #3DD6B0;
    image: url({url});
}}
"""
print("url:", url)
cb.setStyleSheet(qss)

w.show()
QTimer.singleShot(300, lambda: w.grab().save(str(Path(__file__).parent.parent / "assets/_preview2/checkbox_image_test.png")))
QTimer.singleShot(500, app.quit)
app.exec()
print("saved checkbox_image_test.png")
