#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散步（walk）行为数据层：pace 踱步剧本的序列构造与逐帧窗口位移表。

背景：pace 素材是"坐→起身→朝左走→停→坐→起身→转身→朝右走"的完整剧本
（192 帧 @24fps），含两次真实转身。历史教训：硬造循环帧（walk_r_*，质心
对齐 + 交叉淡化）必产生鬼影/顿挫，已退役。现改为整段播放素材原始帧，
窗口按猫在画布内的质心位移同步平移——猫走窗走、猫停窗停、转身原地转，
朝向与移动方向永远一致。

序列 = pace_1..192 原帧 + pace_72..92 镜像（"朝右走减速→停下→坐"收尾），
共 213 帧 ≈ 8.9s。镜像轮整体水平翻转（先右后左），由 main.py 随机选择。
"""
PACE_MIR_AT = 192   # 序列中从此索引起为镜像减速收尾段
PACE_SCALE_K = 12   # 跟随放大系数（画布内质心位移 ×12）
_DX_CLIP = 14       # 单帧位移钳制（画布坐标）
_SMOOTH_W = 4       # 低通半窗宽：滤单帧重心摆动，保留 0.3s 以上速度趋势

# 由 tools 脚本从 sprites/pace_*.png 的 alpha 质心差分预计算（K=12，低通+钳制），
# 运行时乘 scale(显示宽/512) 得像素位移。镜像轮整体取反。
PACE_DX = [
    0, -1, -2, -2, -2, -3, -6, -6, -6, -6, -8, -6, -7, -5, -4, -1, 0, 2,
    1, 2, 3, 2, 5, 6, 8, 7, 3, 3, 2, 1, 4, 0, 0, -1, -3, 0, 0, 0, -5, -7,
    -8, -10, -10, -9, -13, -14, -14, -10, -9, -9, -9, -8, -8, -4, -3, -1,
    -4, -7, -13, -11, -13, -14, -14, -14, -14, -14, -14, -14, -14, -14,
    -14, -10, -11, -12, -14, -9, -9, -7, -6, -2, -1, 0, 3, 8, 7, 10, 9,
    10, 9, 7, 3, 2, 0, -2, -9, -10, -12, -14, -12, -9, -11, -9, -8, -4,
    -4, -2, -1, -2, -2, 0, 0, 0, 0, 2, 4, 6, 4, 6, 9, 10, 11, 12, 14, 13,
    13, 14, 13, 10, 8, 7, 4, 0, 0, -2, -2, -3, -4, -5, -8, -7, -10, -13,
    -14, -14, -14, -14, -14, -11, -9, -4, 5, 14, 14, 14, 14, 14, 14, 14,
    14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14, 14,
    14, 14, 12, 5, 3, 1, 2, 2, 1, 0, 1, 0, 1, 1, 1, 1, 4, 4, 4, 5, 9, 8,
    9, 7, 6, 2, 1, 0, -3, -8, -7, -10, -9, -10, -10, -11, -10, -10,
]


def build_walk_seq(pace_frames, mirror):
    """由已加载的 pace QPixmap 帧构造散步序列。

    pace_frames: pace_01..pace_192 的 QPixmap 列表（192 项）
    mirror(pixmap)->pixmap: 水平镜像函数（QTransform.scale(-1,1)）
    返回 (walk_seq, walk_seq_mir)
    """
    assert len(pace_frames) == 192, f"pace 帧数异常: {len(pace_frames)}"
    tail = [mirror(p) for p in pace_frames[71:92]]     # pace_72..92 镜像收尾
    seq = list(pace_frames) + tail
    return seq, [mirror(p) for p in seq]


def recompute_dx(sprites_dir):
    """从散帧重算 PACE_DX（供生成/校验脚本调用；运行时不走此路径）"""
    import cv2
    import numpy as np
    seq = list(range(1, 193)) + list(range(72, 93))
    cxs = []
    for i in seq:
        fn = sprites_dir / (f"pace_{i:02d}.png" if i < 100 else f"pace_{i}.png")
        a = cv2.imread(str(fn), cv2.IMREAD_UNCHANGED)[:, :, 3]
        ys, xs = np.nonzero(a > 40)
        cxs.append(float(xs.mean()))
    cxs = np.array(cxs)
    raw = np.zeros(len(seq))
    raw[1:] = (cxs[1:] - cxs[:-1]) * PACE_SCALE_K
    for k in range(PACE_MIR_AT, len(seq)):
        raw[k] = -raw[k]
    raw[PACE_MIR_AT] = 0        # 衔接拍：窗口停一拍（猫调头瞬间）
    out = raw.copy()
    for k in range(len(raw)):
        lo, hi = max(0, k - _SMOOTH_W), min(len(raw), k + _SMOOTH_W + 1)
        out[k] = raw[lo:hi].mean()
    return [max(-_DX_CLIP, min(_DX_CLIP, int(v))) for v in out]


assert len(PACE_DX) == 213 and max(abs(v) for v in PACE_DX) <= _DX_CLIP
