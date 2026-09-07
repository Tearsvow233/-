# -*- coding: utf-8 -*-
"""离屏验证 ChatInputDialog：无宠物名/标题行文字，且保留输入提示与确定/取消。
用法：python tools/test_chat_input_title.py
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
sys.argv = ["test_chat_input_title"]

from PySide6.QtWidgets import QApplication, QPushButton, QLabel  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

import main as m  # noqa: E402

failures = []


def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (("  " + str(extra)) if extra else ""))
    if not cond:
        failures.append(name)


app = QApplication.instance() or QApplication(sys.argv)
app.setStyleSheet(m.DIALOG_QSS)  # 模拟 main() 里的全局主题

# 改名后（如“咪咪”）仍不应影响标题 —— 该对话框与 pet_name 零耦合
for renamed in ("小江", "咪咪", "小柯"):
    dlg = m.ChatInputDialog()
    title = dlg.windowTitle()
    check(f"window_title_empty_{renamed}", title == "" and "小江" not in title
          and renamed not in title, repr(title))

    labels = [w.text() for w in dlg.findChildren(QLabel)]
    buttons = [w.text() for w in dlg.findChildren(QPushButton)]
    check("label_hint_present", any("说点什么：" == t for t in labels), labels)
    check("buttons_ok_cancel", buttons == ["确定", "取消"], buttons)

    dlg.show()
    app.processEvents()
    check("default_is_ok", any(b.isDefault() and b.text() == "确定"
                               for b in dlg.findChildren(QPushButton)))

    # Enter -> accept；Esc -> reject
    dlg.edit.setText("  摸摸我  ")
    QTest.keyClick(dlg, Qt.Key.Key_Return)
    check("enter_accepts", dlg.result() == int(m.QDialog.DialogCode.Accepted),
          dlg.result())
    check("text_stripped", dlg.text() == "摸摸我", repr(dlg.text()))
    dlg.close()

    dlg2 = m.ChatInputDialog()
    dlg2.show()
    QTest.keyClick(dlg2, Qt.Key.Key_Escape)
    check("esc_rejects", dlg2.result() == int(m.QDialog.DialogCode.Rejected),
          dlg2.result())
    dlg2.close()
    dlg.deleteLater()
    dlg2.deleteLater()

print("\nTITLE TEST RESULT:", "ALL PASS" if not failures else
      f"{len(failures)} FAILED: {failures}")
sys.exit(1 if failures else 0)
