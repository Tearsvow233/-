# -*- coding: utf-8 -*-
"""动作权重调度验收测试（交接包 T7）。

验收基线：
1. 加权随机：30% 待机 / 10% 转向 / 40% 动作 / 20% 移动（2 万次采样，容差断言）
2. 防连续重复：exclude=上一个动作，连续两次不播同一动作（类别内多选项时）
3. 分布可统计验证：固定种子可复现，频率与理论值对表

附加保障：
4. 类别内剔除后为空的死锁保护（单一选项仍可播）
5. 缺素材类别自动重新归一（pace 缺失 → 其余类别按权重分摊）
6. 空 available / 全 0 权重等边界
"""
import random
import sys
from pathlib import Path

sys.path.insert(0, ".")
import action_scheduler as asc  # noqa: E402

PASS = []
FAIL = []
N = 20000  # 采样次数（σ≈0.32%，容差取 4σ 以上）


def check(name, ok, info=""):
    tag = "PASS" if ok else "FAIL"
    PASS.append(name) if ok else FAIL.append(name)
    print(f"[{tag}] {name} {info}")


ALL = ["stretch", "walk_circle", "groom", "spin", "pace"]


def freq_dist(available=ALL, last=None, **kw):
    rng = random.Random(42)
    counts = {}
    nones = 0
    for _ in range(N):
        r = asc.pick_behavior(list(available), last, rng=rng, **kw)
        if r is None:
            nones += 1
        else:
            counts[r] = counts.get(r, 0) + 1
    return {k: v / N for k, v in counts.items()}, nones / N


def near(p, expect, tol):
    return abs(p - expect) <= tol, f"{p:.4f} vs {expect:.4f} (±{tol})"


def main_():
    print("=" * 60)
    print("T7 动作权重调度验收")
    print("=" * 60)

    # --- 1. 类别权重分布（last=None 时不剔除，理论值纯净） ---
    f, none_p = freq_dist()
    ok, info = near(none_p, 0.30, 0.015)
    check("1a 待机占比 30%", ok, info)
    ok, info = near(f.get("walk_circle", 0), 0.10, 0.010)  # turn 类
    check("1b 转向(walk_circle) 10%", ok, info)
    action_total = sum(f.get(a, 0) for a in ("stretch", "groom", "spin"))
    ok, info = near(action_total, 0.40, 0.015)
    check("1c 原地动作合计 40%", ok, info)
    for a in ("stretch", "groom", "spin"):  # 类别内默认均匀：40%/3
        ok, info = near(f.get(a, 0), 0.40 / 3, 0.010)
        check(f"1d {a} ≈ 13.33%", ok, info)
    ok, info = near(f.get("pace", 0), 0.20, 0.012)
    check("1e 移动(pace) 20%", ok, info)
    check("1f 概率归一", abs(sum(f.values()) + none_p - 1.0) < 1e-9, "")

    # --- 2. 防连续重复 ---
    rng = random.Random(7)
    last, dup = None, 0
    for _ in range(N):
        r = asc.pick_behavior(ALL, last, rng=rng)
        if r is not None:
            if r == last:
                dup += 1
            last = r
    check("2 防连续重复零命中", dup == 0,
          f"{dup} 次连续重复" if dup else f"{N} 次采样")

    # --- 3. 固定种子可复现 ---
    r1 = [asc.pick_behavior(ALL, None, rng=random.Random(99)) for _ in range(50)]
    r2 = [asc.pick_behavior(ALL, None, rng=random.Random(99)) for _ in range(50)]
    check("3 固定种子可复现", r1 == r2, "")

    # --- 4. 死锁保护：类别内只剩上一个动作时仍可播 ---
    rng = random.Random(5)
    hits = sum(1 for _ in range(2000)
               if asc.pick_behavior(["stretch"], "stretch", rng=rng) == "stretch")
    # available=[stretch] → live = idle(30) + action(40) → P(stretch)=40/70≈0.571
    ok, info = near(hits / 2000, 0.40 / 0.70, 0.035)
    check("4 单一选项死锁保护", ok, info)

    # --- 5. 缺素材类别重新归一（pace 缺失 → 剩余 30/10/40 归一） ---
    f2, none2 = freq_dist(available=["stretch", "walk_circle", "groom", "spin"])
    ok, info = near(none2, 0.30 / 0.80, 0.015)
    check("5a pace 缺失后待机 37.5%", ok, info)
    ok, info = near(f2.get("walk_circle", 0), 0.10 / 0.80, 0.012)
    check("5b 转向 12.5%", ok, info)

    # --- 6. 边界 ---
    check("6a 空 available 返回 None",
          all(asc.pick_behavior([], None, rng=random.Random(1)) is None
              for _ in range(100)), "")
    f3, none3 = freq_dist(category_weights={"idle": 0, "turn": 0, "action": 1, "move": 0})
    check("6b 全 0 权重外类别退化均匀", none3 == 0.0 and abs(sum(f3.values()) - 1.0) < 1e-9, "")
    f4, _ = freq_dist(action_weights={"stretch": 3, "groom": 1, "spin": 0})
    ok, info = near(f4.get("stretch", 0) / (f4.get("stretch", 0) + f4.get("groom", 0)),
                    0.75, 0.02)
    check("6c 类别内自定义权重 3:1 生效", ok, info)
    check("6d spin 权重 0 不出现", f4.get("spin", 0) == 0.0, "")

    print("-" * 60)
    print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        for name in FAIL:
            print(f"  - {name}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
