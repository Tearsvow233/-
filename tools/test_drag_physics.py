# -*- coding: utf-8 -*-
"""T10 拖拽物理 —— 独立验收脚本（无 PySide6 依赖）。

用法：python tools/test_drag_physics.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PASS, FAIL = "[PASS]", "[FAIL]"
_results = []


def check(cond, label):
    print(f"  {PASS if cond else FAIL} {label}")
    _results.append(bool(cond))
    return 0 if cond else 1


def section(name):
    print(f"\n=== {name} ===")


def test_pure_logic_no_qt():
    section("纯逻辑层：无 PySide6 依赖")
    import drag_physics as dp
    src = open(dp.__file__, encoding="utf-8").read()
    n = 0
    n += check("import PySide6" not in src, "无 import PySide6")
    n += check("import PyQt" not in src, "无 import PyQt")
    return n


def test_release_velocity():
    section("释放速度：采样窗口")
    import drag_physics as dp
    from drag_physics import DragPhysics
    p = DragPhysics()
    # 100ms 内向右移动 60px → 600 px/s
    p.start_drag(100, 100, t=0.0)
    for i in range(6):
        p.feed(100 + i * 12, 100, t=0.02 * i)
    vx, vy, flying = p.release()
    check(flying, "600 px/s 触发飞行")
    n = 0
    n += check(abs(vx - 600) < 30, f"vx≈600（实际 {vx:.0f}）")
    n += check(abs(vy) < 1, f"vy≈0（实际 {vy:.0f}）")
    return n


def test_gentle_release():
    section("轻放：低速释放不飞行")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(100, 100, t=0.0)
    for i in range(6):
        p.feed(100 + i * 2, 100, t=0.05 * i)  # 250ms 移 10px ≈ 40 px/s
    vx, vy, flying = p.release()
    return check(not flying, "40 px/s 视为轻放")
    _ = (vx, vy)


def test_old_samples_ignored():
    section("采样窗口：只看最近 100ms")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(0, 0, t=0.0)
    p.feed(1000, 0, t=0.5)      # 半秒前的快速移动（窗口外）
    p.feed(1002, 0, t=0.55)
    p.feed(1004, 0, t=0.6)      # 最近 50ms 只挪了 2px → 40 px/s
    vx, vy, flying = p.release()
    return check(not flying, "旧的高速采样被丢弃，判定轻放")


def test_gravity_and_ground_bounce():
    section("重力 + 落地反弹")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(500, 100, t=0.0)
    p.feed(500, 100, t=0.02)
    p.feed(500, 100, t=0.04)
    p.set_bounds(0, 0, 1000, 500)   # 宠物可移动区：底 500
    vx, vy, flying = p.release()
    assert not flying  # 采样全在同一位置 → 轻放；手动注入速度测飞行
    p.state = "flying"
    p.vx, p.vy = 0.0, 500.0
    n = 0
    dt = 0.016
    steps = 0
    max_y = 0.0
    while p.state == "flying" and steps < 5000:
        x, y = p.step(dt)
        max_y = max(max_y, y)
        steps += 1
    n += check(p.state == "idle", f"最终静止（{steps} 步）")
    n += check(abs(p.y - 500) < 1.0, f"停在地面 y={p.y:.1f}（应=500）")
    n += check(p.bounce_count() >= 1, f"至少反弹 1 次（实际 {p.bounce_count()}）")
    n += check(max_y <= 500.0 + 0.01, "从未穿透地面")
    return n


def test_wall_bounce():
    section("左右墙反弹")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(900, 100, t=0.0)
    p.feed(900, 100, t=0.02)
    p.feed(900, 100, t=0.04)
    p.set_bounds(0, 0, 1000, 500)
    p.state = "flying"
    p.vx, p.vy = 1500.0, 0.0   # 高速向右
    n = 0
    steps = 0
    while p.state == "flying" and steps < 3000:
        x, y = p.step(0.016)
        steps += 1
    n += check(p.state == "idle", f"最终静止（{steps} 步，x={p.x:.0f}）")
    n += check(0.0 <= p.x <= 1000.0, f"停在边界内 x={p.x:.1f}（0~1000）")
    n += check(abs(p.y - 500) < 1.0, f"贴地静止 y={p.y:.1f}")
    n += check(p.bounce_count() >= 1, f"至少撞墙/落地 1 次（实际 {p.bounce_count()}）")
    return n


def test_max_speed_clamp():
    section("速度上限")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(0, 0, t=0.0)
    p.feed(3000, 0, t=0.02)    # 150000 px/s，远超上限
    p.feed(3000, 0, t=0.04)
    vx, vy, flying = p.release()
    n = 0
    n += check(flying, "触发飞行")
    n += check(abs(vx) <= 4000 + 0.01, f"vx 被限到 ≤4000（实际 {vx:.0f}）")
    return n


def test_catch_mid_flight():
    section("飞行中抓取")
    from drag_physics import DragPhysics
    p = DragPhysics()
    p.start_drag(500, 100, t=0.0)
    p.feed(500, 100, t=0.02)
    p.feed(500, 100, t=0.04)
    p.set_bounds(0, 0, 1000, 500)
    p.state = "flying"
    p.vx, p.vy = 1000.0, -800.0
    p.step(0.016)
    check(p.state == "flying", "正在飞行")
    p.catch()
    n = check(p.state == "idle", "catch() 立即停止物理")
    x, y = p.step(0.016)
    n += check(p.state == "idle", "catch 后 step 是空操作")
    return n


def test_invalid_bounds():
    section("非法 bounds 拒绝")
    from drag_physics import DragPhysics
    p = DragPhysics()
    try:
        p.set_bounds(100, 0, 50, 500)
        return check(False, "right < left 应抛 ValueError")
    except ValueError:
        return check(True, "right < left 抛 ValueError")


def main():
    print("=" * 60)
    print("T10 拖拽物理 验收")
    print("=" * 60)
    fails = 0
    fails += test_pure_logic_no_qt()
    fails += test_release_velocity()
    fails += test_gentle_release()
    fails += test_old_samples_ignored()
    fails += test_gravity_and_ground_bounce()
    fails += test_wall_bounce()
    fails += test_max_speed_clamp()
    fails += test_catch_mid_flight()
    fails += test_invalid_bounds()
    print()
    total = len(_results)
    if all(_results):
        print(f"ALL PASS · {total} 项全过")
        return 0
    bad = total - sum(_results)
    print(f"FAIL · {bad}/{total} 项不通过")
    return 1


if __name__ == "__main__":
    sys.exit(main())
