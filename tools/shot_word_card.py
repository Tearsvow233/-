# -*- coding: utf-8 -*-
"""为项目展示文档生成「今日单词」词卡实拍图（离屏渲染）"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer
from main import DIALOG_QSS
from word_push import WordCardDialog, load_words

app = QApplication(sys.argv)
app.setStyleSheet(DIALOG_QSS)

words = load_words()
# 取真实词库中读音/释义友好的几条做展示
sample = [w for w in words if w["word"] in
          ("abandon", "cancel", "achieve", "balance", "campus", "confident")][:6]
if len(sample) < 6:
    sample = words[:6]

dlg = WordCardDialog(sample, title="今日单词")
dlg.show()

def snap():
    out = Path(__file__).parent.parent / "assets/_probe/word_card_preview.png"
    dlg.grab().save(str(out))
    print("saved", out, dlg.width(), "x", dlg.height())
    app.quit()

QTimer.singleShot(500, snap)
app.exec()
