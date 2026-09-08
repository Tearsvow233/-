# -*- coding: utf-8 -*-
"""T10 拖拽物理 —— pytest 版（tools/test_drag_physics.py 的 CI 适配）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from drag_physics import (DragPhysics, STATE_IDLE, STATE_DRAGGING,
                          STATE_FLYING, MAX_SPEED)


class TestNoQt:
    def test_no_pyside6_import(self):
        import drag_physics as dp
        src = Path(dp.__file__).read_text(encoding="utf-8")
        assert "import PySide6" not in src
        assert "import PyQt" not in src


class TestRelease:
    def test_fast_release_flies(self):
        p = DragPhysics()
        p.start_drag(100, 100, t=0.0)
        for i in range(6):
            p.feed(100 + i * 12, 100, t=0.02 * i)
        vx, vy, flying = p.release()
        assert flying
        assert abs(vx - 600) < 30
        assert abs(vy) < 1

    def test_gentle_release_no_fly(self):
        p = DragPhysics()
        p.start_drag(100, 100, t=0.0)
        for i in range(6):
            p.feed(100 + i * 2, 100, t=0.05 * i)  # ~40 px/s
        _, _, flying = p.release()
        assert not flying
        assert p.state == STATE_IDLE

    def test_stale_samples_outside_window(self):
        p = DragPhysics()
        p.start_drag(0, 0, t=0.0)
        p.feed(1000, 0, t=0.5)      # 窗口外的高速
        p.feed(1002, 0, t=0.55)
        p.feed(1004, 0, t=0.6)
        _, _, flying = p.release()
        assert not flying

    def test_speed_clamped(self):
        p = DragPhysics()
        p.start_drag(0, 0, t=0.0)
        p.feed(3000, 0, t=0.02)
        p.feed(3000, 0, t=0.04)
        vx, _, flying = p.release()
        assert flying
        assert abs(vx) <= MAX_SPEED + 0.01

    def test_release_without_drag_is_noop(self):
        p = DragPhysics()
        assert p.release() == (0.0, 0.0, False)

    def test_single_sample_no_fly(self):
        p = DragPhysics()
        p.start_drag(0, 0, t=0.0)
        _, _, flying = p.release()
        assert not flying


class TestFlight:
    def _fly(self, vx, vy, bounds=(0, 0, 1000, 500)):
        p = DragPhysics()
        p.start_drag(500, 100, t=0.0)
        p.feed(500, 100, t=0.02)
        p.feed(500, 100, t=0.04)
        if bounds:
            p.set_bounds(*bounds)
        p.state = STATE_FLYING
        p.vx, p.vy = vx, vy
        return p

    def test_falls_and_settles_on_ground(self):
        p = self._fly(0.0, 500.0)
        steps = 0
        while p.state == STATE_FLYING and steps < 5000:
            p.step(0.016)
            steps += 1
        assert p.state == STATE_IDLE
        assert abs(p.y - 500) < 1.0
        assert p.bounce_count() >= 1

    def test_never_penetrates_ground(self):
        p = self._fly(0.0, 1200.0)
        for _ in range(3000):
            p.step(0.016)
            assert p.y <= 500.0 + 0.01
            if p.state == STATE_IDLE:
                break

    def test_wall_bounce_stays_in_bounds(self):
        p = self._fly(1500.0, 0.0)
        steps = 0
        while p.state == STATE_FLYING and steps < 3000:
            p.step(0.016)
            steps += 1
        assert p.state == STATE_IDLE
        assert 0.0 <= p.x <= 1000.0     # 弹墙后可能停在中途
        assert abs(p.y - 500) < 1.0    # 贴地静止

    def test_top_boundary_bounces_down(self):
        p = self._fly(0.0, -2000.0)
        for _ in range(200):
            p.step(0.016)
            assert p.y >= -0.01
            if p.state == STATE_IDLE:
                break

    def test_catch_stops_flight(self):
        p = self._fly(1000.0, -800.0)
        p.step(0.016)
        assert p.state == STATE_FLYING
        p.catch()
        assert p.state == STATE_IDLE
        p.step(0.016)
        assert p.state == STATE_IDLE

    def test_no_bounds_settles_on_low_speed(self):
        p = self._fly(10.0, 5.0, bounds=None)
        for _ in range(2000):
            p.step(0.016)
            if p.state == STATE_IDLE:
                break
        assert p.state == STATE_IDLE

    def test_dt_clamped(self):
        p = self._fly(0.0, 800.0)
        for _ in range(50):
            p.step(5.0)   # 荒谬大 dt
            assert p.y <= 500.0 + 0.01


class TestBounds:
    def test_invalid_bounds_raises(self):
        p = DragPhysics()
        with pytest.raises(ValueError):
            p.set_bounds(100, 0, 50, 500)
        with pytest.raises(ValueError):
            p.set_bounds(0, 100, 500, 50)


class TestStateMachine:
    def test_states_constants(self):
        assert STATE_IDLE == "idle"
        assert STATE_DRAGGING == "dragging"
        assert STATE_FLYING == "flying"
