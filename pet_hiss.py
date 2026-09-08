# -*- coding: utf-8 -*-
"""哈气动画：超过 60 秒没点过猫 → 下一次点击在猫身边播一遍哈气视频。

与 main.py 的边界：
- 本模块自包含门控 + 播放器，main.py 零改动（行数红线踩线）；
- pet_drag.py 的单击分支调 try_play(pet)：返回 True 表示本次点击已消费
  （播哈气），False 走原有 start_react() 反应；
- 视频资源 assets/hiss.mp4（AI 生成，已随 spec datas 打进 exe）。

播放器：QMediaPlayer + QVideoWidget 的无边框置顶小窗（带声音），
播完/出错自动关闭；解码器缺失等异常静默降级（返回 False，落回普通反应）。
"""
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
HISS_VIDEO = _BASE / "assets" / "hiss.mp4"
HISS_GAP_SEC = 60.0        # 距上次点击超过该秒数，下次点击触发
LOG_HOOK = None            # main 注入 log()；未注入时降级 stderr


def _log(msg):
    if LOG_HOOK is not None:
        LOG_HOOK(msg)
    else:
        print(msg, file=sys.stderr)


def should_hiss(last_click_ts, now=None, threshold=HISS_GAP_SEC):
    """纯函数：距上次点击是否已超过 threshold 秒（供测试/复用）"""
    if now is None:
        now = time.time()
    try:
        return (now - float(last_click_ts)) >= float(threshold)
    except (TypeError, ValueError):
        return False


class HissPlayer(QObject):
    """哈气视频播放器：懒构造，一个进程内复用一个窗口。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._win = None        # 播放窗口（None=未创建/已关闭）
        self._player = None
        self._audio = None

    def _build(self):
        """构造窗口与播放器；QtMultimedia 不可用返回 False"""
        try:
            from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
            from PySide6.QtMultimediaWidgets import QVideoWidget
        except Exception as exc:
            _log(f"[hiss] QtMultimedia 不可用：{exc}")
            return False
        self._win = QWidget()
        self._win.setWindowFlags(Qt.WindowType.FramelessWindowHint
                                 | Qt.WindowType.WindowStaysOnTopHint
                                 | Qt.WindowType.Tool)
        self._win.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._video = QVideoWidget(self._win)
        self._player = QMediaPlayer(self._win)
        self._audio = QAudioOutput(self._win)
        self._player.setVideoOutput(self._video)
        self._player.setAudioOutput(self._audio)
        self._player.errorOccurred.connect(self._on_error)
        self._player.mediaStatusChanged.connect(self._on_status)
        return True

    def _on_error(self, _err, msg):
        _log(f"[hiss] 播放出错：{msg}")
        self.close()

    def _on_status(self, status):
        from PySide6.QtMultimedia import QMediaPlayer
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self.close()

    def close(self):
        if self._player is not None:
            try:
                self._player.stop()
            except RuntimeError:
                pass
        if self._win is not None:
            try:
                self._win.close()
                self._win.deleteLater()
            except RuntimeError:
                pass
        self._win = None
        self._player = None
        self._audio = None

    def is_playing(self):
        try:
            return self._win is not None and self._win.isVisible()
        except RuntimeError:
            self._win = None
            return False

    def play(self, pet):
        """在猫旁边播一遍；返回是否成功开播。窗口高度≈猫高×2，宽度按 16:9。"""
        if self.is_playing():
            return False
        if not HISS_VIDEO.exists():
            _log(f"[hiss] 视频缺失：{HISS_VIDEO}")
            return False
        if not self._build():
            return False
        h = max(200, min(int(pet.height() * 2), 340))
        w = int(h * 16 / 9)
        self._win.resize(w, h)
        self._video.resize(w, h)
        self._player.setSource(QUrl.fromLocalFile(str(HISS_VIDEO)))
        self._win.show()
        # 窗口放猫头顶居中，并夹回屏幕
        g = self._win.frameGeometry()
        g.moveCenter(pet.geometry().center())
        g.moveTop(max(0, pet.geometry().top() - h - 10))
        self._win.move(g.topLeft())
        try:
            screen = pet.screen() or QGuiApplication.primaryScreen()
            ag = screen.availableGeometry()
            wg = self._win.geometry()
            if wg.right() > ag.right():
                wg.moveRight(ag.right())
            if wg.left() < ag.left():
                wg.moveLeft(ag.left())
            if wg.bottom() > ag.bottom():
                wg.moveBottom(ag.bottom())
            if wg.top() < ag.top():
                wg.moveTop(ag.top())
            self._win.setGeometry(wg)
        except Exception as exc:
            _log(f"[hiss] 夹屏失败：{exc}")
        self._player.play()
        _log("[hiss] 哈气动画播放")
        return True


_player = HissPlayer()


def try_play(pet, threshold=HISS_GAP_SEC):
    """点击入口：满足"超时未点"且猫醒着且非静默模式才播。

    无论是否触发都会刷新 _last_click_ts（这次点击本身就是互动）；
    基线取 _app_start_ts（进程启动时刻），首次点击不凭空触发。
    """
    now = time.time()
    last = getattr(pet, "_last_click_ts", None) or getattr(pet, "_app_start_ts", 0.0)
    pet._last_click_ts = now
    if not should_hiss(last, now, threshold):
        return False
    if pet._is_sleeping():
        return False
    if pet.settings.get("mode", "normal") == "silent":
        return False
    return _player.play(pet)
