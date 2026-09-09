# -*- coding: utf-8 -*-
"""图集化 sprite sheet 构建工具（交接包 T3）。

把 assets/sprites/ 的 500 张散装帧 PNG 合并成按动作分组的横幅图集
（assets/atlases/），加载时一次读入再 copy() 切帧，消除每文件 ~6ms 的
QPixmap 加载固定开销。

- 分组：misc（idle/walk/click 单帧）+ 每个 ACTIONS 动作一组
- 分片：单片宽度上限 8192px（规避纹理宽度限制，与 strip 缓存一致）
- 索引：atlas_index.json 记录 每帧 -> [图集文件, x, y, w, h]
- 无损：PNG 拼接不重采样，构建后逐帧像素校验与源图完全一致

用法：
  python tools/build_atlas.py --dry-run   # 只统计，不落盘
  python tools/build_atlas.py             # 构建图集 + 索引 + 校验
  python tools/build_atlas.py --verify    # 只校验现有图集与源图一致
"""
import json
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).resolve().parent.parent
SPRITES_DIR = BASE / "assets" / "sprites"
ATLAS_DIR = BASE / "assets" / "atlases"
INDEX_FILE = ATLAS_DIR / "atlas_index.json"

MAX_STRIP_W = 16384  # 单片宽度上限（px）：512 高时 33MB/片，raster 下安全

# 与 main.py 的 _frame_names() 保持一致的单帧清单
# （walk_r_* 已退役：散步改播 pace 原始剧本，见 main.py PACE_DX 说明）
SINGLES = ["idle_open.png", "idle_blink.png",
           "click_surprise.png", "click_happy.png"]

# 与 main.py ACTIONS 定义顺序一致（此处只需键序列）
ACTIONS = ["sleep", "stretch", "walk_circle", "wake", "groom",
           "settle", "recoil", "spin", "pace",
           "eat", "drink", "play", "hiss"]


def collect_groups():
    """返回 [(组名, [帧名...]), ...]，顺序与 _frame_names() 一致"""
    groups = [("misc", list(SINGLES))]
    for act in ACTIONS:
        frames = []
        i = 1
        while (SPRITES_DIR / f"{act}_{i:02d}.png").exists():
            frames.append(f"{act}_{i:02d}.png")
            i += 1
        if frames:
            groups.append((act, frames))
    return groups


def shard(frames):
    """按宽度上限把帧序列切成若干片：[[帧名...], ...]"""
    strips, cur, cur_w = [], [], 0
    for name in frames:
        with Image.open(SPRITES_DIR / name) as im:
            w, _ = im.size
        if cur and cur_w + w > MAX_STRIP_W:
            strips.append(cur)
            cur, cur_w = [], 0
        cur.append(name)
        cur_w += w
    if cur:
        strips.append(cur)
    return strips


def build(dry=False):
    groups = collect_groups()
    total = sum(len(f) for _, f in groups)
    total_bytes = sum((SPRITES_DIR / n).stat().st_size
                      for _, fs in groups for n in fs)
    print(f"共 {len(groups)} 组 / {total} 帧 / 源体积 {total_bytes/1048576:.1f} MB")

    n_files = sum(len(shard(fs)) for _, fs in groups)
    print(f"分片后图集文件数: {n_files}（上限 {MAX_STRIP_W}px 宽/片）")
    if dry:
        for g, fs in groups:
            print(f"  {g:12s} {len(fs):3d} 帧 -> {len(shard(fs))} 片")
        print("dry-run：未写盘")
        return

    ATLAS_DIR.mkdir(parents=True, exist_ok=True)
    index = {"version": 1, "max_strip_w": MAX_STRIP_W, "frames": {}, "order": []}
    for gname, fs in groups:
        for si, strip in enumerate(shard(fs)):
            # 先解码本片全部帧，取统一画布高度（取最大，通常都是 512）
            ims = {n: Image.open(SPRITES_DIR / n).convert("RGBA") for n in strip}
            hh = max(im.height for im in ims.values())
            canvas = Image.new("RGBA", (sum(im.width for im in ims.values()), hh),
                              (0, 0, 0, 0))
            x = 0
            for n in strip:
                im = ims[n]
                canvas.paste(im, (x, 0))
                fname = f"{gname}_{si:02d}.png"
                index["frames"][n] = [fname, x, 0, im.width, im.height]
                index["order"].append(n)
                x += im.width
            out = ATLAS_DIR / f"{gname}_{si:02d}.png"
            canvas.save(out, "PNG", optimize=True, compress_level=9)
            for im in ims.values():
                im.close()
        print(f"  {gname:12s} {len(fs):3d} 帧 -> {len(shard(fs))} 片 完成")

    with open(INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    print(f"索引写入 {INDEX_FILE}")
    atlas_bytes = sum(p.stat().st_size for p in ATLAS_DIR.glob('*.png'))
    print(f"图集总体积 {atlas_bytes/1048576:.1f} MB（源 {total_bytes/1048576:.1f} MB）")


def verify():
    """逐帧校验：图集切片与源图像素完全一致（PNG 无损拼接的前提）"""
    with open(INDEX_FILE, encoding="utf-8") as f:
        index = json.load(f)
    atlas_cache = {}
    bad = 0
    for name, (fname, x, y, w, h) in index["frames"].items():
        src = Image.open(SPRITES_DIR / name).convert("RGBA")
        if fname not in atlas_cache:
            atlas_cache[fname] = Image.open(ATLAS_DIR / fname).convert("RGBA")
        crop = atlas_cache[fname].crop((x, y, x + w, y + h))
        if crop.tobytes() != src.tobytes() or crop.size != src.size:
            print(f"  [FAIL] {name} 与源图不一致")
            bad += 1
        src.close()
    n = len(index["frames"])
    print(f"校验 {n} 帧: {'ALL PASS' if bad == 0 else f'{bad} 帧不一致'}")
    return bad == 0


if __name__ == "__main__":
    if "--verify" in sys.argv:
        sys.exit(0 if verify() else 1)
    build(dry="--dry-run" in sys.argv)
