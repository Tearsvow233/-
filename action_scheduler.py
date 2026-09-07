# -*- coding: utf-8 -*-
"""动作权重调度（交接包 T7）——纯逻辑层，零 Qt。

两级加权随机：
1. 类别级（默认权重，参照原项目调度配比）：
   idle 待机 30% / turn 转向 10% / action 原地动作 40% / move 移动 20%
2. 类别内：按动作 weight 加权

防连续重复（exclude）：从所有类别中剔除上一个动作后再抽——
类别权重随之自动重归一（如刚播过 pace，move 类整体让位，20% 分摊给其余）。
死锁保护：剔除后若只剩待机（素材池只有这一个动作），回退允许重复。

BabyCat 无独立转向素材，turn 暂映射到 walk_circle（转圈走动）；
素材增补后只需改 CATEGORY_ACTIONS，无需动 main.py。

分布可统计验证（tools/test_action_scheduler.py：2 万次采样 + 容差断言）。
"""
import random

# 类别权重（相对权重，总和不必为 100）
CATEGORY_WEIGHTS = {"idle": 30, "turn": 10, "action": 40, "move": 20}

# 类别 -> 动作名（动作名须与 main.ACTIONS 的键一致）
CATEGORY_ACTIONS = {
    "idle": [],                       # 待机 = 什么都不播，返回 None
    "turn": ["walk_circle"],
    "action": ["stretch", "groom", "spin"],
    "move": ["pace"],
}

# 类别内动作权重（默认全 1，即类别内均匀）
ACTION_WEIGHTS = {name: 1
                  for acts in CATEGORY_ACTIONS.values() for name in acts}


def _live_categories(ca, avail, exclude=None):
    """可用类别表 [(类别, 可选动作)]；exclude 命中的动作被剔除。
    idle 恒在（无动作选项也算可响应）；其余类别须剔完后仍有动作。"""
    live = []
    for cat, acts in ca.items():
        opts = [a for a in acts if a in avail]
        if exclude is not None:
            opts = [a for a in opts if a != exclude]
        if cat == "idle" or opts:
            live.append((cat, opts))
    return live


def pick_behavior(available, last=None, *, rng=None,
                   category_weights=None, category_actions=None,
                   action_weights=None):
    """挑一个自动行为。

    返回动作名；返回 None 表示"待机"（本轮不播任何动作）。
    available:            当前有素材、可播的动作名（list/set）
    last:                 上一个播出的动作名（防连续重复；None=无）
    rng:                  随机源（注入 random.Random(seed) 便于统计验证）
    category_weights / category_actions / action_weights: 覆盖默认配置
    """
    rng = rng if rng is not None else random
    cw = dict(CATEGORY_WEIGHTS if category_weights is None else category_weights)
    ca = (CATEGORY_ACTIONS if category_actions is None
          else {k: list(v) for k, v in category_actions.items()})
    aw = dict(ACTION_WEIGHTS if action_weights is None else action_weights)

    avail = set(available)
    if not avail:
        return None

    # 严格模式：全局剔除 last；死锁保护：只剩待机则回退允许重复
    live = _live_categories(ca, avail, exclude=last)
    if all(not opts for _, opts in live):
        live = _live_categories(ca, avail)
    if not live:
        return None

    cats = [c for c, _ in live]
    weights = [cw.get(c, 0) for c in cats]
    if sum(weights) <= 0:                      # 权重全 0 → 退化成均匀
        weights = [1] * len(cats)
    cat = rng.choices(cats, weights=weights, k=1)[0]

    options = dict(live)[cat]
    if not options:                            # idle：本轮待机
        return None
    w = [max(aw.get(a, 1), 0) for a in options]
    if sum(w) <= 0:
        w = [1] * len(options)
    return rng.choices(options, weights=w, k=1)[0]
