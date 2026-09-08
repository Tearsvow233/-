# -*- coding: utf-8 -*-
"""每日英语单词推送 —— 词库加载 / 选词 / 进度 / 词卡弹窗（独立模块）。

与 main.py 的边界：
- 本模块只依赖 PySide6 与标准库，不含宠物状态机；
- 词卡窗口（WordCardDialog）供 main.PetWindow 弹给用户，统一走全局 DIALOG_QSS；
- 选词/进度逻辑是纯函数，可被 tools/test_word_push.py 离屏反复测试。

词库结构（assets/words/cet4_core.json）：
    [{"word": "...", "phonetic": "/.../", "meaning": "...", "example": "可选"}, ...]
其中 word/phonetic/meaning 非空为硬性要求，加载时会过滤不合格项。
"""
import html
import json
import random
import sys
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

# 词库资源路径：开发态在项目目录；打包后被 PyInstaller 放进只读 _MEIPASS。
_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


def words_data_path():
    """词库 JSON 的完整路径（打包后需与 BabyCat.spec datas 保持同步）"""
    return _BASE / "assets" / "words" / "cet4_core.json"


# ---------------------------------------------------------------------------
# 词库加载
# ---------------------------------------------------------------------------
def load_words(path=None):
    """加载并校验词库，返回合格词条列表；文件缺失/损坏返回空列表（调用方兜底）。

    硬性过滤：必须是 dict 且 word/phonetic/meaning 三个字段 strip 后非空；
    按 word 小写去重（保留先出现者）；example 仅保留非空字符串。
    """
    p = Path(path) if path else words_data_path()
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for e in raw:
        if not isinstance(e, dict):
            continue
        w = str(e.get("word") or "").strip()
        ph = str(e.get("phonetic") or "").strip()
        m = str(e.get("meaning") or "").strip()
        if not (w and ph and m):
            continue
        low = w.lower()
        if low in seen:
            continue
        seen.add(low)
        item = {"word": w, "phonetic": ph, "meaning": m}
        ex = e.get("example")
        if isinstance(ex, str) and ex.strip():
            item["example"] = ex.strip()
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# 每日选词：date 种子 → 连续 N 词，全表轮转
# ---------------------------------------------------------------------------
_EPOCH = date(2026, 1, 1)   # 固定纪元，保证同一天两次调用结果一致


def today_str(day=None):
    """归一为 'YYYY-MM-DD' 字符串；day 可为 None/date/datetime/字符串"""
    if day is None:
        day = datetime.now()
    if isinstance(day, datetime):
        return day.strftime("%Y-%m-%d")
    if isinstance(day, date):
        return day.strftime("%Y-%m-%d")
    return str(day)


def day_index_for(day_str):
    """日期字符串距离固定纪元的天数；解析失败退化为稳定 hash（仅兜底）"""
    try:
        d = datetime.strptime(today_str(day_str), "%Y-%m-%d").date()
        return (d - _EPOCH).days
    except Exception:
        return abs(hash(day_str)) % (2 ** 31)


def pick_words(words, day=None, count=10):
    """按日期取『连续 N 词』：每天起点前进 N 位、对词表总长取模。

    - 同一天重复调用返回同一批词（date 种子确定性）；
    - 一日内不重复（count 不超过总长时窗口内天然无重复）；
    - 全表约 ceil(total/count) 天跑完一轮后轮转（默认词库 2607 词 × 10/天 ≈ 261 天）。
    """
    total = len(words)
    if total <= 0:
        return []
    count = max(1, min(int(count), total))
    ds = today_str(day)
    start = (day_index_for(ds) * count) % total
    return [words[(start + i) % total] for i in range(count)]


# ---------------------------------------------------------------------------
# 本地进度：跟随 settings 的语义放 exe 旁（words_progress.json），跨日自动重置
# ---------------------------------------------------------------------------
_EMPTY_PROGRESS = {"date": "", "pushed": False, "words": [],
                   "batch_done": 0, "last_push_ts": 0.0}


def load_progress(path):
    """读取进度文件；不存在/损坏回退为空进度。

    旧格式迁移：无 batch_done 字段且当天已推 → 视为全部批次已推完
    （旧版一次推完整天，语义等价）；未推过 → batch_done=0。
    """
    base = dict(_EMPTY_PROGRESS)
    p = Path(path)
    if not p.exists():
        return base
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return base
    if not isinstance(data, dict):
        return base
    words = data.get("words") or []
    if not isinstance(words, list):
        words = []
    done = data.get("batch_done")
    if not isinstance(done, int) or done < 0:
        done = (len(words) + BATCH_SIZE - 1) // BATCH_SIZE \
            if (data.get("pushed") and words) else 0
    try:
        last_ts = float(data.get("last_push_ts") or 0.0)
    except (TypeError, ValueError):
        last_ts = 0.0
    return {
        "date": str(data.get("date") or ""),
        "pushed": bool(data.get("pushed")),
        "words": [dict(w) for w in words if isinstance(w, dict)],
        "batch_done": done,
        "last_push_ts": last_ts,
    }


def save_progress(path, progress):
    """写进度文件（path 由 main 提供 exe 旁的完整路径）"""
    Path(path).write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def pushed_today(progress, day=None):
    """当天是否已推送（date 与今日一致且 pushed 为真且留有词）"""
    ds = today_str(day)
    return (progress.get("date") == ds and bool(progress.get("pushed"))
            and bool(progress.get("words")))


def plan_words(words, progress, day=None, count=10):
    """推进"每日一次"逻辑：已规划 → 原样返回今日词；未规划 → 选词并写新进度。

    返回 (今日词列表, 新进度)。纯函数，不落盘；写盘由调用方负责。
    新进度带批次字段（batch_done=0 / last_push_ts=0），分批推送从第 0 批开始。
    """
    prog = dict(progress)
    ds = today_str(day)
    if pushed_today(prog, ds):
        return list(prog["words"]), prog
    sel = pick_words(words, ds, count)
    prog = {"date": ds, "pushed": True, "words": sel,
            "batch_done": 0, "last_push_ts": 0.0}
    return sel, prog


# ---------------------------------------------------------------------------
# 分批推送：当天词量切成 2 词一批，09:00~20:30 间到点弹小气泡卡
# ---------------------------------------------------------------------------
BATCH_SIZE = 2            # 每批词数（小气泡卡一次只学得动这么多）
MIN_GAP_SEC = 25 * 60     # 两批之间的最小间隔（补推防连发）
_WINDOW_START = 9 * 60            # 推送窗口起点 09:00（分钟）
_WINDOW_END = 20 * 60 + 30        # 推送窗口终点 20:30


def batches_for(words, size=BATCH_SIZE):
    """把当天词列表切成若干批（每批 size 个，最后一批可能不足）"""
    ws = list(words)
    return [ws[i:i + size] for i in range(0, len(ws), size)]


def batch_times(day_str, n):
    """第 i 批的计划推送时刻（datetime 列表，同一天重复调用结果一致）。

    均匀分布在 09:00~20:30，±15 分钟确定性抖动（日期+批数做种子），
    避免每天准点机械弹窗。
    """
    d = datetime.strptime(today_str(day_str), "%Y-%m-%d").date()
    rng = random.Random(day_index_for(day_str) * 131 + int(n))
    out = []
    for i in range(max(1, int(n))):
        mid = _WINDOW_START + (_WINDOW_END - _WINDOW_START) * (i + 0.5) / n
        t = int(round(mid + rng.uniform(-15, 15)))
        t = max(_WINDOW_START, min(_WINDOW_END, t))
        out.append(datetime.combine(d, dtime(t // 60, t % 60)))
    return out


def due_batch(progress, now=None):
    """当前是否到点该推下一批；到点返回批次下标，否则 None。

    条件：当天已规划、还有未推批次、计划时刻已过、距上批 ≥ MIN_GAP_SEC。
    错过的批次按“尽快补推”处理（受最小间隔限制，不会连发）。
    """
    if now is None:
        now = datetime.now()
    if not pushed_today(progress):
        return None
    batches = batches_for(progress.get("words") or [])
    done = int(progress.get("batch_done") or 0)
    if not batches or done >= len(batches):
        return None
    if now < batch_times(progress["date"], len(batches))[done]:
        return None
    last = float(progress.get("last_push_ts") or 0.0)
    if last and now.timestamp() - last < MIN_GAP_SEC:
        return None
    return done


def any_pushed_today(progress, day=None):
    """当天是否已推出过至少一批（托盘「今日单词」可用性）"""
    return pushed_today(progress, day) and int(progress.get("batch_done") or 0) > 0


def words_pushed_so_far(progress):
    """当天已推出批次的词（回看用，按推送顺序展开）"""
    done = int(progress.get("batch_done") or 0)
    return [w for b in batches_for(progress.get("words") or [])[:done] for w in b]


# ---------------------------------------------------------------------------
# 发音：优先 QtTextToSpeech（离线 SAPI），兜底 PowerShell System.Speech
# ---------------------------------------------------------------------------
LOG_HOOK = None   # main 注入 log()；未注入时降级 print 到 stderr
_tts = None
_tts_failed = False


def _log(msg):
    if LOG_HOOK is not None:
        LOG_HOOK(msg)
    else:
        print(msg, file=sys.stderr)


def speak_word(word):
    """朗读单词；全部路径不可用则记日志并返回 False（不打扰用户）。"""
    global _tts, _tts_failed
    w = (word or "").strip()
    if not w:
        return False
    if not _tts_failed:
        try:
            if _tts is None:
                from PySide6.QtTextToSpeech import QTextToSpeech
                _tts = QTextToSpeech()
            _tts.say(w)
            return True
        except Exception as exc:
            _tts_failed = True
            _log(f"[word] QtTextToSpeech 不可用，转 PowerShell 兜底：{exc}")
    try:
        import subprocess
        safe = w.replace("'", "''")
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "Add-Type -AssemblyName System.Speech; "
             f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe}')"],
            creationflags=0x08000000)   # CREATE_NO_WINDOW
        return True
    except Exception as exc:
        _log(f"[word] 发音兜底也失败：{exc}")
        return False


def _clickable_word_html(word):
    """单词的富文本：点击触发发音（linkActivated → say:协议）"""
    esc = html.escape(word)
    return (f'<a href="say:{esc}" style="color:#7FD8FF;text-decoration:none;">'
            f'<span style="font-size:16px;font-weight:600;">{esc}</span></a>'
            f' <span style="font-size:11px;color:#5F5F70;">🔊</span>')


def _on_say_link(href):
    """词卡/气泡里的 say: 链接统一入口"""
    if isinstance(href, str) and href.startswith("say:"):
        speak_word(html.unescape(href[4:]))


# ---------------------------------------------------------------------------
# 词卡弹窗（暗色玻璃统一风格；标题不含宠物名）
# ---------------------------------------------------------------------------
class WordCardDialog(QDialog):
    """滚动词卡：单词加粗 + 音标灰色 + 中文释义，有例句则展示例句。

    非模态展示（由 main 调 show()），窗口置顶但 WA_ShowWithoutActivating，
    弹出来不抢用户当前窗口焦点；尺寸参考 PetCenter：内容最小宽度兜底、
    禁用横向滚动、显示时夹回屏幕内。
    """

    def __init__(self, words, title="每日单词", parent=None):
        super().__init__(parent)
        self._words = [dict(w) for w in words]
        self.setWindowTitle(title)
        self.setMinimumWidth(340)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        head = QLabel("📖 " + title)
        head.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #F0F0F6; background: transparent;"
        )
        outer.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        container = QWidget()
        body = QVBoxLayout(container)
        body.setContentsMargins(2, 2, 10, 2)
        body.setSpacing(4)

        if not self._words:
            empty = QLabel("今天没有可展示的词喵~")
            empty.setWordWrap(True)
            body.addWidget(empty)
        else:
            for i, w in enumerate(self._words):
                self._append_word_row(body, w)
                if i < len(self._words) - 1:
                    sep = QFrame()
                    sep.setFrameShape(QFrame.Shape.HLine)
                    sep.setStyleSheet(
                        "background: #3A3A46; border: none; max-height: 1px;"
                    )
                    body.addSpacing(2)
                    body.addWidget(sep)
                    body.addSpacing(2)
        body.addStretch(1)

        scroll.setWidget(container)
        # 词行文字按深色主题配色（亮字灰标），容器必须给深色底，否则浅底浅字不可读
        container.setStyleSheet("background-color: #23232E;")
        scroll.viewport().setStyleSheet("background-color: #23232E;")
        outer.addWidget(scroll, 1)

        btns = QHBoxLayout()
        done = QPushButton("今天先这样")
        done.setDefault(True)
        done.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(done)
        outer.addLayout(btns)

        self._fit_geometry(scroll, container)

    # ---------- 词行 ----------
    def _append_word_row(self, layout, w):
        ph = html.escape(w.get("phonetic") or "")
        meaning = html.escape(w.get("meaning") or "")
        example = w.get("example")
        if isinstance(example, str):
            example = html.escape(example.strip())

        l1 = QLabel(
            _clickable_word_html(w.get("word") or "")
            + f' <span style="font-size:13px;color:#8E8E9E;">{ph}</span>'
        )
        l1.setTextFormat(Qt.TextFormat.RichText)
        l1.setOpenExternalLinks(False)
        l1.linkActivated.connect(_on_say_link)
        l1.setToolTip("点击单词听发音")
        l1.setWordWrap(True)
        layout.addWidget(l1)

        if meaning:
            lm = QLabel(
                f'<span style="font-size:13px;color:#E8E8F0;">{meaning}</span>'
            )
            lm.setTextFormat(Qt.TextFormat.RichText)
            lm.setWordWrap(True)
            layout.addWidget(lm)

        if example:
            le = QLabel(
                f'<span style="font-size:12px;color:#9A9AA8;font-style:italic;">'
                f"例：{example}</span>"
            )
            le.setTextFormat(Qt.TextFormat.RichText)
            le.setWordWrap(True)
            layout.addWidget(le)

    # ---------- 尺寸适配（内容最小宽度兜底 / 不横向滚动 / 高度封顶） ----------
    def _fit_geometry(self, scroll, container):
        try:
            screen = QApplication.primaryScreen().availableGeometry()
        except Exception:
            screen = None
        try:
            body = container.layout()
            body.activate()
            need_w = container.minimumSizeHint().width()
            vbar_w = scroll.verticalScrollBar().sizeHint().width() or 12
            limit = max(340, (screen.width() - 40)) if screen else 1200
            fit_w = max(int(need_w) + vbar_w + 6, 340)
            fit_w = min(fit_w, limit)

            n = len(self._words)
            est_h = 96 + n * 54 + 40                # 顶栏+每词+按钮的粗估
            cap_h = min(int(screen.height() * 0.85), 640) if screen else 640
            h = max(240, min(est_h, cap_h))
            if screen and screen.height() - 20 < h:
                h = max(200, screen.height() - 20)

            self.setMinimumWidth(fit_w)
            self.resize(min(fit_w + 24, (screen.width() - 20) if screen else fit_w + 24), h)
        except Exception:
            pass

    def clamp_to_screen(self):
        """把窗口夹回屏幕内（参考 PetCenter 经验）；showEvent 与 post-show move 后均需调用"""
        try:
            parent = self.parentWidget()
            scr = (parent.screen() if (parent and parent.screen())
                   else QApplication.primaryScreen())
            ag = scr.availableGeometry()
            g = self.geometry()
            if g.right() > ag.right():
                g.moveRight(ag.right())
            if g.left() < ag.left():
                g.moveLeft(ag.left())
            if g.bottom() > ag.bottom():
                g.moveBottom(ag.bottom())
            if g.top() < ag.top():
                g.moveTop(ag.top())
            self.setGeometry(g)
        except Exception:
            pass

    def showEvent(self, event):
        super().showEvent(event)
        self.clamp_to_screen()

    # 供测试/回看使用
    @property
    def words(self):
        return list(self._words)


# ---------------------------------------------------------------------------
# 小气泡词卡：一批 1~2 词，猫头顶弹出，45s 自动关闭
# ---------------------------------------------------------------------------
class WordBubble(QDialog):
    """分批推送用的小词卡：单词(可点发音)+音标+释义(+例句)，不抢焦点。

    与 WordCardDialog 的差别：无滚动区、固定小尺寸、自动关闭——
    出现在猫旁边像猫"叼"出来的一张小卡片，看完即走。
    """

    AUTO_CLOSE_MS = 45 * 1000

    def __init__(self, words, batch_no=1, batch_total=1, parent=None):
        super().__init__(parent)
        self._words = [dict(w) for w in words]
        self.setWindowTitle(f"单词时间 · {batch_no}/{batch_total}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(6)

        head = QLabel(f"📖 单词时间 <span style='color:#8E8E9E;font-size:11px;'>"
                      f"第 {batch_no}/{batch_total} 批 · 点单词听发音</span>")
        head.setStyleSheet(
            "font-size: 13px; font-weight: bold; color: #F0F0F6; background: transparent;"
        )
        head.setTextFormat(Qt.TextFormat.RichText)
        outer.addWidget(head)

        for i, w in enumerate(self._words):
            self._append_word_row(outer, w)
            if i < len(self._words) - 1:
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.HLine)
                sep.setStyleSheet("background: #3A3A46; border: none; max-height: 1px;")
                outer.addWidget(sep)

        self.setMinimumWidth(300)
        self.setStyleSheet("background-color: #23232E;")
        self.adjustSize()
        cap_h = 260
        if self.height() > cap_h:
            self.resize(self.width(), cap_h)

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self.accept)
        self._auto_timer.start(self.AUTO_CLOSE_MS)

    _append_word_row = WordCardDialog._append_word_row   # 词行渲染复用

    def clamp_to_screen(self):
        """弹到猫头顶后可能越界，夹回屏幕内"""
        try:
            parent = self.parentWidget()
            scr = (parent.screen() if (parent and parent.screen())
                   else QApplication.primaryScreen())
            ag = scr.availableGeometry()
            g = self.geometry()
            if g.right() > ag.right():
                g.moveRight(ag.right())
            if g.left() < ag.left():
                g.moveLeft(ag.left())
            if g.bottom() > ag.bottom():
                g.moveBottom(ag.bottom())
            if g.top() < ag.top():
                g.moveTop(ag.top())
            self.setGeometry(g)
        except Exception as exc:
            _log(f"[word] 气泡夹屏失败：{exc}")

    @property
    def words(self):
        return list(self._words)
