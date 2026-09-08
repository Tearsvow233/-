# -*- coding: utf-8 -*-
"""T8 主动观察的 Qt 集成层（从 main.py 拆出，T5 行数预算红线）。

组成：
- VisionWorker           后台线程调视觉模型
- foreground_process_path ctypes 取前台进程（零新依赖，仅 Windows）
- VisionMixin            PetWindow 的观察/决策/展示方法
- build_vision_form()    灵宠中心的 T8 设置控件（main.py 装配用）
- collect_vision_values() 从控件收集 settings 值

依赖方向：UI 层 → 纯逻辑层（proactive_vision / ai_chat）；禁止反向。
log 通过运行时从 main 导入（公开接口，无私有面访问）。
"""
import base64
import sys
import time
import traceback

from PySide6.QtCore import Qt, QThread, QTimer, Signal, QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import QCheckBox, QSpinBox, QLineEdit

from proactive_vision import IdleDetector, dhash, process_allowed


class VisionWorker(QThread):
    """T8：后台线程调视觉模型（截图 → 一句主动搭话），不卡 UI。"""
    result_ready = Signal(object)   # str 或 None（None/出错 -> 静默放弃）

    def __init__(self, ai, image_b64, prompt):
        super().__init__()
        self.ai = ai
        self.image_b64 = image_b64
        self.prompt = prompt

    def run(self):
        try:
            ans = self.ai.reply_vision(self.image_b64, self.prompt)
        except Exception:
            ans = None
        self.result_ready.emit(ans)


def foreground_process_path():
    """当前前台进程的可执行文件完整路径；取不到返回 None（非 Windows / 无权限）。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
            return None
        finally:
            kernel32.CloseHandle(h)
    except Exception:
        return None


class VisionMixin:
    """PetWindow 的主动观察能力。宿主需提供：
    settings / ai / bubble / state / last_touch_ts / current_screen() /
    _is_sleeping() / _sleep_pending / _chat_busy
    """

    # 提示词：只做"看一眼 + 一句话"，禁提问、限字数，别把主人隐私细节复述出来
    _VISION_PROMPT = (
        "主人面前这个画面已经停留很久了。你看一眼截图，"
        "用一句话可爱地关心或调侃一下主人正在做的事（比如该休息了/又在肝代码），"
        "不要复述画面里的具体内容和个人信息，不要提问，不超过30字。"
    )

    def _init_vision(self):
        # T8 主动行为：定时截 9×8 缩略图做哈希，画面+人闲置才触发视觉搭话
        self._vision = IdleDetector(
            stable_ticks=max(1, int(self.settings.get("vision_idle_min", 10)
                                    * 60 / max(5, self.settings.get("vision_check_sec", 60)))),
            cooldown_sec=max(60, self.settings.get("vision_cooldown_min", 30) * 60),
        )
        self._vision_busy = False           # 视觉调用进行中（防重入）
        self.vision_timer = QTimer(self)
        self.vision_timer.timeout.connect(self._on_vision_tick)
        if (self.settings.get("proactive_vision", False)
                and self.settings.get("ai_enabled")):
            self.vision_timer.start(max(5, self.settings.get("vision_check_sec", 60)) * 1000)

    def _apply_vision_settings(self):
        """灵宠中心保存后调用：按新设置启停观察定时器。"""
        on = (self.settings.get("proactive_vision", False)
              and self.settings.get("ai_enabled"))
        check_sec = max(5, int(self.settings.get("vision_check_sec", 60)))
        if on:
            self.vision_timer.start(check_sec * 1000)
        else:
            self.vision_timer.stop()

    def _grab_gray_thumb(self):
        """当前屏 → 9×8 灰度字节（dHash 输入）。失败返回 None。

        只取 72 字节的极低清缩略图：判闲置够用，本身不含可读信息。
        """
        from main import log
        try:
            from PySide6.QtGui import QImage
            img = (self.current_screen().grabWindow(0)
                   .toImage()
                   .convertToFormat(QImage.Format.Format_Grayscale8)
                   .scaled(9, 8, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.FastTransformation))
            w, bpl = img.width(), img.bytesPerLine()
            data = bytes(img.constBits())
            return b"".join(data[y * bpl: y * bpl + w] for y in range(8))
        except Exception:
            log(f"[error] 缩略图截图失败:\n{traceback.format_exc()}")
            return None

    def _grab_jpeg_b64(self, max_w=1024, quality=70):
        """当前屏截图 → 等比缩到 max_w 内 → JPEG base64。失败返回 None。"""
        from main import log
        try:
            from PySide6.QtGui import QImage
            img = self.current_screen().grabWindow(0).toImage()
            if img.width() > max_w:
                img = img.scaledToWidth(max_w, Qt.TransformationMode.SmoothTransformation)
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            img.save(buf, "JPG", quality)
            return base64.b64encode(bytes(ba)).decode("ascii")
        except Exception:
            log(f"[error] 截图编码失败:\n{traceback.format_exc()}")
            return None

    def _on_vision_tick(self):
        """观察节拍：截缩略图 → 哈希 → 闲置判定 → 白名单 → 视觉模型。"""
        from main import log
        try:
            now = time.time()
            s = self.settings
            if not (s.get("proactive_vision") and s.get("ai_enabled")):
                return
            # 睡眠/拖拽/已有调用在跑/正在聊天 → 不打扰
            if (self._is_sleeping() or self._sleep_pending or self.state == "drag"
                    or self._vision_busy or self._chat_busy):
                return
            if self._vision.in_cooldown(now):
                return
            # 人也得闲置：最近 vision_idle_min 内没摸过猫
            idle_sec = max(60, s.get("vision_idle_min", 10) * 60)
            if now - self.last_touch_ts < idle_sec:
                return
            # 画面闲置：连续 N 帧哈希不变（边沿触发，只在进入闲置那一刻为 True）
            thumb = self._grab_gray_thumb()
            if thumb is None:
                return
            if not self._vision.update(dhash(thumb), now):
                return
            # 隐私红线：前台进程命中白名单才允许把截图送模型
            proc = foreground_process_path()
            if not process_allowed(proc, s.get("vision_process_whitelist") or []):
                log(f"[vision] 前台进程 {proc!r} 不在白名单，跳过本次主动观察")
                return
            b64 = self._grab_jpeg_b64()
            if not b64:
                return
            # 无论模型成败都先记冷却，避免失败时连环截图重试
            self._vision.notify_chat(now)
            self._vision_busy = True
            self._vision_worker = VisionWorker(self.ai, b64, self._VISION_PROMPT)
            self._vision_worker.result_ready.connect(self._on_vision_result)
            self._vision_worker.finished.connect(lambda: setattr(self, "_vision_busy", False))
            self._vision_worker.start()
        except Exception:
            # 观察循环绝不带崩主程序（红线：不吞异常 → 记日志后继续下一拍）
            log(f"[error] 主动行为 tick 异常:\n{traceback.format_exc()}")

    def _on_vision_result(self, ans):
        """视觉模型回复 → 气泡；失败静默（下一轮冷却后再试）。"""
        from main import log
        if not ans or str(ans).startswith("__ERR__"):
            log(f"[vision] 视觉模型调用失败，本次放弃: {ans!r}")
            return
        ans = str(ans).strip()
        if len(ans) > 60:
            ans = ans[:60] + "…"
        self.bubble.say(ans, (self.x(), self.y(), self.width()), ms=4000)


# ---------- 灵宠中心表单装配（main.py 调用）----------

def build_vision_form(form, settings):
    """把 T8 的 5 个设置控件加进 QFormLayout；返回控件 dict 供 values() 收集。"""
    w = {}
    w["check"] = QCheckBox("主动观察（空闲时看一眼屏幕并搭话，隐私优先）")
    w["check"].setChecked(bool(settings.get("proactive_vision", False)))
    form.addRow("", w["check"])

    w["idle"] = QSpinBox()
    w["idle"].setRange(3, 120)
    w["idle"].setValue(int(settings.get("vision_idle_min", 10)))
    w["idle"].setSuffix(" 分钟")
    form.addRow("└ 静止多久才算空闲", w["idle"])

    w["cool"] = QSpinBox()
    w["cool"].setRange(5, 360)
    w["cool"].setValue(int(settings.get("vision_cooldown_min", 30)))
    w["cool"].setSuffix(" 分钟")
    form.addRow("└ 搭话后冷却", w["cool"])

    w["model"] = QLineEdit(settings.get("ai_vision_model", ""))
    w["model"].setPlaceholderText("留空 = 用上面的模型（需支持图片）")
    form.addRow("└ 视觉模型名", w["model"])

    w["wl"] = QLineEdit(", ".join(settings.get("vision_process_whitelist") or []))
    w["wl"].setPlaceholderText("允许被观察的前台应用，如：chrome, code, idea64")
    form.addRow("└ 应用白名单", w["wl"])
    return w


def collect_vision_values(w):
    """从 build_vision_form 返回的控件收集 settings 值。"""
    return {
        "proactive_vision": w["check"].isChecked(),
        "vision_idle_min": w["idle"].value(),
        "vision_cooldown_min": w["cool"].value(),
        "ai_vision_model": w["model"].text().strip(),
        # 白名单解析：逗号/空格分隔，去空
        "vision_process_whitelist": [x for x in
            w["wl"].text().replace("，", ",").replace(" ", ",").split(",")
            if x.strip()],
    }
