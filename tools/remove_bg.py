# -*- coding: utf-8 -*-
"""
BabyCat 素材工具 v2：自适应背景抠除 + 只保留猫本体 + 裁剪对齐
- 自适应洪水填充：与"来时的邻居像素"比较颜色，容忍渐变背景
- 连通域分析：只保留最大不透明块（猫），水印文字/碎渣全清
- 裁剪到内容包围盒
用法：python tools/remove_bg.py  （自动从 sprites_raw 备份还原后重新处理）
"""

from collections import deque
from pathlib import Path

from PIL import Image

SPRITES = Path(__file__).parent.parent / "assets" / "sprites"
BACKUP = Path(__file__).parent.parent / "assets" / "sprites_raw"
GLOBAL_TOL = 70    # 与全局背景色的距离容忍
NEIGHBOR_TOL = 40  # 与来时邻居颜色的距离容忍（处理渐变）

def dist(a, b):
    return sum(abs(x - y) for x, y in zip(a[:3], b[:3]))

def remove_bg(im: Image.Image) -> Image.Image:
    w, h = im.size
    px = im.load()

    samples = [
        px[2, 2], px[w - 3, 2], px[2, h - 3], px[w - 3, h - 3],
        px[w // 2, 2], px[w // 2, h - 3], px[2, h // 2], px[w - 3, h // 2],
    ]
    bg = tuple(max(set(samples), key=samples.count)[:3])

    visited = bytearray(w * h)
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            q.append((x, y, bg))
    for y in range(h):
        for x in (0, w - 1):
            q.append((x, y, bg))

    while q:
        x, y, ref = q.popleft()
        if x < 0 or x >= w or y < 0 or y >= h:
            continue
        i = y * w + x
        if visited[i]:
            continue
        visited[i] = 1
        cur = px[x, y]
        if dist(cur, bg) > GLOBAL_TOL and dist(cur, ref) > NEIGHBOR_TOL:
            continue  # 前景，不扩散
        px[x, y] = (0, 0, 0, 0)
        q.extend(((x - 1, y, cur), (x + 1, y, cur),
                  (x, y - 1, cur), (x, y + 1, cur)))
    return im

def keep_largest(im: Image.Image) -> Image.Image:
    """连通域分析，只保留最大不透明块，其余清零，再裁剪包围盒"""
    w, h = im.size
    px = im.load()
    visited = bytearray(w * h)
    best = None  # (size, set_of_indices)

    for sy in range(h):
        for sx in range(w):
            i0 = sy * w + sx
            if visited[i0] or px[sx, sy][3] <= 30:
                continue
            comp = []
            q = deque([(sx, sy)])
            visited[i0] = 1
            while q:
                x, y = q.popleft()
                comp.append((x, y))
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h:
                        j = ny * w + nx
                        if not visited[j] and px[nx, ny][3] > 30:
                            visited[j] = 1
                            q.append((nx, ny))
            if best is None or len(comp) > len(best):
                best = comp

    keep = set(y * w + x for x, y in best)
    for y in range(h):
        for x in range(w):
            if y * w + x not in keep and px[x, y][3] > 0:
                px[x, y] = (0, 0, 0, 0)

    bbox = im.getbbox()
    return im.crop(bbox) if bbox else im

def process(path: Path, raw: Path):
    im = raw and Image.open(raw).convert("RGBA") or Image.open(path).convert("RGBA")
    im = remove_bg(im)
    im = keep_largest(im)
    im.save(path)
    print(f"{path.name}: -> {im.size[0]}x{im.size[1]} 完成")

def main():
    BACKUP.mkdir(exist_ok=True)
    for f in sorted(SPRITES.glob("*.png")):
        raw = BACKUP / f.name
        if not raw.exists():
            raw.write_bytes(f.read_bytes())
        process(f, raw)

if __name__ == "__main__":
    main()
