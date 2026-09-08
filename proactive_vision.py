# -*- coding: utf-8 -*-
"""T8 proactive 主动行为：纯逻辑层。

「截图 → 感知哈希比对判闲置 → 视觉模型 → 主动搭话」的决策部分。
零 GUI 依赖（禁 PySide6）：main.py 负责截图/取前台进程（IO），
本模块只做哈希、闲置判定、冷却、白名单判断（纯函数 + 小状态机）。

设计要点（见 docs/ProactiveVision需求.md）：
- dHash（差异哈希）：9×8 灰度图 → 64 bit，屏幕内容变化的鲁棒指纹
- 闲置判定：连续 stable_ticks 次哈希距离 <= max_distance 视为画面静止
- 冷却：主动搭话一次后 cooldown_sec 内不再触发（防骚扰）
- 白名单：只有前台进程命中白名单才允许截图送模型（隐私红线）
"""

# ---- 可调参数（docs/ProactiveVision需求.md §3）----
DHASH_W, DHASH_H = 9, 8          # dHash 网格：宽 9 产生 8 个水平差分
DEFAULT_STABLE_TICKS = 10        # 连续 10 次画面不变 = 闲置（10 × 60s = 10 分钟）
DEFAULT_MAX_DISTANCE = 6          # 哈希汉明距离 <= 6 视为"没变化"
DEFAULT_COOLDOWN_SEC = 1800.0     # 主动搭话后 30 分钟冷却


def dhash(gray_bytes, width=DHASH_W, height=DHASH_H):
    """9×8 灰度字节（行优先，len 必须 == width*height）→ 64 bit 整数。

    每行取相邻两像素的"左 > 右"作为 1 bit。纯逻辑：输入只要求是
    可迭代的长 width*height 字节序列（QImage 灰度扫描线在 main.py 拼好）。
    """
    gray = list(gray_bytes)
    if len(gray) != width * height:
        raise ValueError(f"dhash 需要 {width}*{height}={width * height} 个灰度字节，"
                         f"实际 {len(gray)}")
    bits = 0
    n = 0
    for row in range(height):
        base = row * width
        for col in range(width - 1):
            if gray[base + col] > gray[base + col + 1]:
                bits |= 1 << n
            n += 1
    return bits


def hamming(a, b):
    """两个整数的汉明距离。"""
    return bin(a ^ b).count("1")


class IdleDetector:
    """画面静止判定（小状态机，非线程安全：只在主线程用）。

    每次截图算一个哈希后调 update(h, now)：
    - 返回 True 表示"刚满足闲置条件"（只在从非闲置 → 闲置的边沿触发一次）
    - notify_chat(now) 记录"已主动搭话"，进入冷却
    """

    def __init__(self, stable_ticks=DEFAULT_STABLE_TICKS,
                 max_distance=DEFAULT_MAX_DISTANCE,
                 cooldown_sec=DEFAULT_COOLDOWN_SEC):
        if stable_ticks < 1:
            raise ValueError("stable_ticks 至少为 1")
        self.stable_ticks = int(stable_ticks)
        self.max_distance = int(max_distance)
        self.cooldown_sec = float(cooldown_sec)

        self._last_hash = None
        self._stable_run = 0          # 连续"与上一帧相比没变化"的次数
        self._idle = False             # 当前是否处于闲置态
        self._last_chat_ts = float("-inf")   # 上次主动搭话时间（冷却用）

    def update(self, h, now):
        """喂入当前帧哈希 + 时间戳。返回 True = 闲置条件刚刚满足（边沿触发）。

        stable_ticks 语义 = "连续 N 帧画面基本不变"（含首帧基线，
        即 N 帧只需要 N-1 次比较），与「连续 N 次截图都一样」的直觉一致。
        """
        if self._last_hash is not None and hamming(h, self._last_hash) > self.max_distance:
            self._stable_run = 0       # 画面动了 → 重新计
        self._stable_run += 1          # 本帧计入稳定计数
        self._last_hash = h

        was_idle = self._idle
        self._idle = self._stable_run >= self.stable_ticks

        # 只在"非闲置 → 闲置"的边沿返回 True
        return (not was_idle) and self._idle

    def is_idle(self):
        return self._idle

    def in_cooldown(self, now):
        """冷却期内（刚主动搭话过）返回 True。"""
        return (now - self._last_chat_ts) < self.cooldown_sec

    def notify_chat(self, now):
        """主动搭话已发生：记录时间戳并复位闲置状态（重新观察）。"""
        self._last_chat_ts = float(now)
        self._stable_run = 0
        self._idle = False
        self._last_hash = None


# ---- 进程白名单（隐私红线：命中才允许把截图送模型）----

def process_allowed(process_path_or_name, whitelist):
    """前台进程是否命中白名单。

    process_path_or_name: 完整路径（C:\\...\\Code.exe）或纯名（code.exe）
    whitelist: 进程名列表（可带 .exe 可不带，大小写不敏感；空列表 = 全部拒绝）
    """
    if not process_path_or_name or not whitelist:
        return False
    name = str(process_path_or_name).rsplit("\\", 1)[-1].rsplit("/", 1)[-1].strip().lower()
    if not name:
        return False
    for w in whitelist:
        w = str(w).strip().lower()
        if not w:
            continue
        if not w.endswith(".exe"):
            w = w + ".exe"
        if name == w:
            return True
    return False
