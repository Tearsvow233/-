# -*- coding: utf-8 -*-
"""宠物交互 Mixin：鼠标事件（拖拽/点击/双击）+ T10 拖拽物理的 Qt 集成层。

从 main.py 拆出（T5 行数预算红线）：main.py 只做装配（PetWindow 继承本 Mixin）。
依赖方向：UI 层 → 纯逻辑层（drag_physics）；禁止反向。
log / save_settings 通过运行时从 main 导入（公开接口，无私有面访问）。
"""
import time
import traceback

from PySide6.QtCore import Qt, QTimer

from drag_physics import DragPhysics


class DragMixin:
    """鼠标交互 + 拖拽物理。宿主（PetWindow）需提供：
    settings / bubble / state / current_screen() / set_frame() /
    wake_up() / _is_sleeping() / start_react() / open_chat_input() /
    blink_timer / unblink_timer / react_timer / walk_timer /
    behavior_timer / action_timer / pix_surprise / pix_open /
    schedule_next_blink() / _interval_ms() / last_touch_ts
    """

    def _init_drag_physics(self):
        # T10 拖拽物理：释放后 ~60fps 积分（甩抛/重力/反弹），落地即停
        self._phys = DragPhysics()
        self.physics_timer = QTimer(self)   # 16ms ≈ 60fps
        self.physics_timer.timeout.connect(self._on_physics_tick)
        self._phys_bounced = False          # 本次飞行是否弹跳过（落地播 recoil）

    # ---------- 鼠标：拖拽 + 点击 ----------
    def mousePressEvent(self, event):
        self.last_touch_ts = time.time()
        # T10：飞行中按下 = 空中抓住，立即停止物理
        if self.physics_timer.isActive():
            self.physics_timer.stop()
            self._phys.catch()
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_was_sleep = False
            self._press_pos = event.globalPosition().toPoint()
            self._dragging = False
            self._offset = self._press_pos - self.pos()
            # 睡眠中：不触发普通反应，而是累积"叫醒点击"
            if self._is_sleeping():
                self._press_was_sleep = True
                self._wake_click_count += 1
                if self._wake_click_count >= 3:
                    self.wake_up()
                else:
                    self._wake_click_timer.start(2500)
                    self.bubble.say("呼噜… Zzz…（再点几下叫醒我）",
                                    (self.x(), self.y(), self.width()), ms=1500)

    def mouseDoubleClickEvent(self, event):
        # 双击 = 和小江聊天（单击仍是"被点击反应"）
        self.last_touch_ts = time.time()
        if self._is_sleeping():
            self.wake_up()
        self.open_chat_input()

    def mouseMoveEvent(self, event):
        if not hasattr(self, "_press_pos"):
            return
        gp = event.globalPosition().toPoint()
        # 移动超过 6px 才算拖拽，避免点击误判
        if not self._dragging and (gp - self._press_pos).manhattanLength() > 6:
            # 睡眠中被拎起 → 先唤醒，再进入正常拖拽分支
            if self.state == "sleep" or self._sleep_pending:
                self.wake_up()
            self._dragging = True
            self.state = "drag"
            if self.settings.get("drag_physics", True):
                self._phys.start_drag(gp.x(), gp.y())
            for t in (self.blink_timer, self.unblink_timer, self.react_timer,
                      self.walk_timer, self.behavior_timer, self.action_timer):
                t.stop()
            self.action_name = None
            self._sleep_pending = False
            self.set_frame(self.pix_surprise)  # 被拎起来：瞪圆眼睛
        if self._dragging:
            if self.settings.get("drag_physics", True):
                self._phys.feed(gp.x(), gp.y())
            self.move(gp - self._offset)

    def mouseReleaseEvent(self, event):
        if not hasattr(self, "_press_pos"):
            return
        was_sleep_press = getattr(self, "_press_was_sleep", False)
        if hasattr(self, "_press_was_sleep"):
            del self._press_was_sleep
        if self._dragging:
            # T10：甩抛判定 —— 释放速度够大就飞出去（重力+反弹），落地再收尾
            flew = False
            if self.settings.get("drag_physics", True):
                self._phys.set_bounds(*self._physics_bounds())
                vx, vy, flying = self._phys.release()
                if flying:
                    flew = True
                    self._phys_bounced = False
                    self.state = "drag"      # 维持"被控制"态，落地才回 idle
                    self.physics_timer.start(16)
            if not flew:
                # 轻放 / 物理关闭：原有逻辑（记住位置，回待机）
                self._after_drag_settle()
        else:
            # 原地没动 = 单击 → 触发反应
            # 但睡眠中发起的点击（含凑满 3 次刚唤醒那一下）不做普通反应
            if not was_sleep_press:
                self.start_react()
        self.last_touch_ts = time.time()
        del self._press_pos

    # ---------- T10 拖拽物理 ----------
    def _physics_bounds(self):
        """当前屏可用区域扣除宠物自身宽高 → 宠物左上角可移动范围。"""
        ag = self.current_screen().availableGeometry()
        return (float(ag.left()), float(ag.top()),
                float(ag.right()) - self.width() + 1,
                float(ag.bottom()) - self.height() + 1)

    def _after_drag_settle(self):
        """拖拽/飞行结束的统一收尾：保存位置，回待机。"""
        from main import log, save_settings   # 运行时导入，避免循环依赖
        self.settings["pos_x"], self.settings["pos_y"] = self.x(), self.y()
        save_settings(self.settings)
        self.state = "idle"
        self.set_frame(self.pix_open)
        self.schedule_next_blink()
        if self.settings["auto_walk"]:
            self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))

    def _on_physics_tick(self):
        """飞行积分一帧（~60fps）。落地静止后停表并收尾。"""
        from main import log
        try:
            x, y = self._phys.step(0.016)
            self.move(round(x), round(y))
            if self._phys.bounce_count() > 0:
                self._phys_bounced = True
            if self._phys.state == "idle":
                self.physics_timer.stop()
                bounced = self._phys_bounced
                self._after_drag_settle()
                if bounced:
                    # 摔过一跤：落地播个"吓一跳"反应
                    self.start_react()
        except Exception:
            # 物理循环绝不带崩主程序（项目红线：不吞异常 → 记日志后停表）
            log(f"[error] 拖拽物理帧异常:\n{traceback.format_exc()}")
            self.physics_timer.stop()
            self._after_drag_settle()
