# -*- coding: utf-8 -*-
"""T10 拖拽物理：纯逻辑层。

甩抛 + 重力 + 屏幕边界反弹。零 GUI 依赖（禁 PySide6），
main.py 通过 start_drag/feed/release/step 驱动。

状态机：
    idle ──start_drag──> dragging ──release──> flying（有速度）或 idle（轻放）
    flying ──静止判定──> idle
"""

import time
from collections import deque

# ---- 可调参数（见 docs/拖拽物理需求.md §3）----
GRAVITY = 3000.0          # px/s^2，屏幕坐标系向下为正
RESTITUTION = 0.35        # 垂直反弹系数
WALL_BOUNCE = 0.5         # 水平撞墙反弹系数
GROUND_FRICTION = 0.8     # 每次落地水平速度保留比
MIN_THROW = 350.0         # px/s，低于视为轻放
SAMPLE_WINDOW = 0.10      # s，释放速度采样窗口
MAX_SPEED = 4000.0        # px/s，速度上限
SETTLE_VY = 40.0          # px/s，垂直静止阈值
SETTLE_VX = 20.0          # px/s，水平静止阈值
MAX_DT = 0.05             # s，单步积分上限（防大步长穿透）

STATE_IDLE = "idle"
STATE_DRAGGING = "dragging"
STATE_FLYING = "flying"


class DragPhysics:
    """单只宠物的拖拽物理。非线程安全：只在主线程用。"""

    def __init__(self, gravity=GRAVITY, restitution=RESTITUTION,
                 wall_bounce=WALL_BOUNCE, ground_friction=GROUND_FRICTION,
                 min_throw=MIN_THROW, sample_window=SAMPLE_WINDOW,
                 max_speed=MAX_SPEED):
        self.gravity = float(gravity)
        self.restitution = float(restitution)
        self.wall_bounce = float(wall_bounce)
        self.ground_friction = float(ground_friction)
        self.min_throw = float(min_throw)
        self.sample_window = float(sample_window)
        self.max_speed = float(max_speed)

        self.state = STATE_IDLE
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        # 宠物可移动区域（调用方已减去宠物自身宽高）
        self._bounds = None           # (left, top, right, bottom)
        self._samples = deque()       # [(t, x, y)]，拖拽采样
        self._bounces = 0             # 本次飞行累计反弹次数

    # ---------- 拖拽阶段 ----------
    def start_drag(self, x, y, t=None):
        """按下并确认进入拖拽时调用；清空旧采样。"""
        if t is None:
            t = time.monotonic()
        self.state = STATE_DRAGGING
        self.x, self.y = float(x), float(y)
        self.vx = self.vy = 0.0
        self._samples.clear()
        self._samples.append((t, self.x, self.y))

    def feed(self, x, y, t=None):
        """拖拽过程中每次 mouseMove 采样。"""
        if t is None:
            t = time.monotonic()
        if self.state != STATE_DRAGGING:
            return
        self.x, self.y = float(x), float(y)
        self._samples.append((t, self.x, self.y))
        # 淘汰窗口外的旧采样（保留最近 2 个点保底能算速度）
        while len(self._samples) > 2 and (t - self._samples[0][0]) > self.sample_window:
            self._samples.popleft()

    def release(self):
        """松手：返回 (vx, vy, flying)。

        flying=False 表示轻放（速度低于阈值或采样不足），
        调用方走原有「原地保存」逻辑。
        """
        if self.state != STATE_DRAGGING:
            return 0.0, 0.0, False
        if len(self._samples) < 2:
            self.state = STATE_IDLE
            return 0.0, 0.0, False

        t0, x0, y0 = self._samples[0]
        t1, x1, y1 = self._samples[-1]
        dt = t1 - t0
        if dt <= 0:
            self.state = STATE_IDLE
            return 0.0, 0.0, False

        vx = (x1 - x0) / dt
        vy = (y1 - y0) / dt
        speed = (vx * vx + vy * vy) ** 0.5
        if speed < self.min_throw:
            self.state = STATE_IDLE
            return 0.0, 0.0, False

        # 限速
        if speed > self.max_speed:
            k = self.max_speed / speed
            vx, vy = vx * k, vy * k

        self.vx, self.vy = vx, vy
        self._bounces = 0
        self.state = STATE_FLYING
        return vx, vy, True

    # ---------- 飞行阶段 ----------
    def set_bounds(self, left, top, right, bottom):
        """宠物可移动区域（左上/右下，已扣除宠物自身宽高）。"""
        if right < left or bottom < top:
            raise ValueError("bounds 非法: right < left 或 bottom < top")
        self._bounds = (float(left), float(top), float(right), float(bottom))

    def bounce_count(self):
        """本次飞行累计反弹次数（落地后用于决定是否播 recoil）。"""
        return self._bounces

    def step(self, dt):
        """飞行积分一步（半隐式欧拉），返回 (x, y)。

        静止判定通过 state == STATE_IDLE 得知；此时返回最终落点。
        未设置 bounds 时不反弹（自由落体，一般不会发生）。
        """
        if self.state != STATE_FLYING:
            return self.x, self.y

        dt = min(max(dt, 0.0), MAX_DT)
        if dt == 0.0:
            return self.x, self.y

        if self._bounds is None:
            # 无边界（保险路径，正常调用方总是先 set_bounds）：
            # 进入本帧时双向低速 → 直接静止。
            # 必须在加重力之前判定 —— 自由落体的 vy 只会越来越大，
            # 放在重力之后判定会导致低速释放永不静止（无限下坠）。
            if abs(self.vx) < SETTLE_VX and abs(self.vy) < SETTLE_VY:
                self._settle()
                return self.x, self.y

        # 重力
        self.vy += self.gravity * dt

        # 位置积分
        self.x += self.vx * dt
        self.y += self.vy * dt

        if self._bounds is not None:
            left, top, right, bottom = self._bounds
            # 左右墙
            if self.x < left:
                self.x = left
                self.vx = abs(self.vx) * self.wall_bounce
                if abs(self.vx) > 1.0:
                    self._bounces += 1
            elif self.x > right:
                self.x = right
                self.vx = -abs(self.vx) * self.wall_bounce
                if abs(self.vx) > 1.0:
                    self._bounces += 1
            # 顶部（往下弹）
            if self.y < top:
                self.y = top
                self.vy = abs(self.vy) * self.restitution
                self._bounces += 1
            # 地面
            on_ground = False
            if self.y >= bottom:
                self.y = bottom
                self.vy = -abs(self.vy) * self.restitution
                self.vx *= self.ground_friction
                if abs(self.vy) > SETTLE_VY * 0.5:
                    self._bounces += 1
                on_ground = True

            # 静止判定：贴地 + 双向低速
            if on_ground and abs(self.vy) < SETTLE_VY and abs(self.vx) < SETTLE_VX:
                self._settle()

        return self.x, self.y

    def _settle(self):
        self.vx = self.vy = 0.0
        self.state = STATE_IDLE

    # ---------- 辅助 ----------
    def catch(self):
        """飞行中被抓住（mousePress 打断物理）。"""
        self.state = STATE_IDLE
        self._samples.clear()
        self.vx = self.vy = 0.0
