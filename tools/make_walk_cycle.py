#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从 pace_144..191（朝右行走段，24fps 原速提取）生成无缝向右行走循环帧。

处理步骤：
1. 逐帧对齐 alpha 质心 x（消除素材内前进位移，使循环"原地化"）；y 不动，保留身体起伏。
2. 循环接缝（末帧→首帧）做 4 帧交叉淡化，把首尾姿态跳变摊薄到正常帧差量级。
3. 输出 assets/sprites/walk_r_01.png .. walk_r_52.png（48 循环帧 + 4 过渡帧）。

用法： tools/make_walk_cycle.py
"""
import os
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPR = os.path.join(ROOT, "assets", "sprites")

LO, HI = 144, 191          # pace 行走稳定段（含）
XREF = 256                 # 质心对齐目标（画布中心）
FADE = 4                   # 接缝过渡帧数


def pace_path(i: int) -> str:
    return os.path.join(SPR, f"pace_{i:02d}.png" if i < 100 else f"pace_{i}.png")


def load_frames() -> list:
    frames = []
    for i in range(LO, HI + 1):
        img = cv2.imread(pace_path(i), cv2.IMREAD_UNCHANGED)
        if img is None or img.shape[2] != 4:
            raise SystemExit(f"读取失败或无 alpha: {pace_path(i)}")
        frames.append((i, img))
    return frames


def centroid_x(img) -> float:
    a = img[:, :, 3]
    xs = np.nonzero(a > 40)[1]
    return float(xs.mean()) if len(xs) else XREF


def shift_x(img, dx: int):
    if dx == 0:
        return img
    out = np.zeros_like(img)
    if dx > 0:   # 右移：内容右移 dx 像素
        out[:, dx:] = img[:, :512 - dx]
    else:
        out[:, :512 + dx] = img[:, -dx:]
    return out


def main() -> None:
    frames = load_frames()

    # 1) x 质心对齐到画布中心（整数平移，保持像素原样）
    aligned = []
    for i, img in frames:
        dx = round(XREF - centroid_x(img))
        aligned.append((i, shift_x(img, dx)))

    # 2) 接缝交叉淡化：t_k = (1-k/5)*末帧 + (k/5)*首帧
    first = aligned[0][1].astype(float)
    last = aligned[-1][1].astype(float)
    tail = []
    for k in range(1, FADE + 1):
        w = k / (FADE + 1)
        blended = (last * (1 - w) + first * w).astype(np.uint8)
        tail.append(blended)

    # 3) 落盘：walk_r_01..48 为循环帧，49..52 为过渡帧
    seq = [img for _, img in aligned] + tail
    total = len(seq)
    for idx, img in enumerate(seq, start=1):
        out = os.path.join(SPR, f"walk_r_{idx:02d}.png")
        ok = cv2.imwrite(out, img)
        if not ok:
            raise SystemExit(f"写入失败: {out}")
    print(f"OK 生成 walk_r_01..{total:02d}.png（{LO}-{HI} 对齐 + {FADE} 过渡帧）")

    # 4) 自检：接缝质量对比（淡入前 vs 淡化后残差）
    def d(a, b):
        return float(np.abs(a.astype(float) - b.astype(float)).mean())
    raw_seam = d(aligned[-1][1], aligned[0][1])
    residual = d(tail[-1], aligned[0][1])
    inner = np.mean([d(aligned[k][1], aligned[k + 1][1]) for k in range(len(aligned) - 1)])
    print(f"原始接缝差={raw_seam:.4f}  淡化后残差={residual:.4f}  平均相邻差={inner:.4f}"
          f"  （残差/相邻差 ≈ {residual / inner:.1f}x，原为 {raw_seam / inner:.1f}x）")


if __name__ == "__main__":
    main()
