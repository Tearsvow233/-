"""量化各精灵图的猫体包围盒，检查脚底基线/水平中心是否一致（影响动作切换是否"跳位"）。"""
from pathlib import Path
from PIL import Image
import glob

SPRITES = Path(r"D:\agent\BabyCat\assets\sprites")

def bbox(path):
    im = Image.open(path).convert("RGBA")
    w, h = im.size
    px = im.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 20:  # alpha 阈值
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return None
    return dict(w=w, h=h, left=minx, top=miny, right=maxx, bottom=maxy,
               cx=(minx+maxx)/2, feet=maxy, cat_h=maxy-miny)

def report(group):
    files = sorted(glob.glob(str(SPRITES / f"{group}_*.png")))
    if not files:
        # 可能是 idle/walk 单图
        files = sorted(glob.glob(str(SPRITES / f"{group}.png")))
    print(f"\n=== {group} ({len(files)} 帧) ===")
    if not files:
        print("  (无)")
        return
    feets, cxs = [], []
    for f in files:
        b = bbox(Path(f))
        if b is None:
            print(f"  {Path(f).name}: 全透明?"); continue
        feets.append(b["feet"]); cxs.append(b["cx"])
        print(f"  {Path(f).name:18s} 脚底y={b['feet']:4d} 中心x={b['cx']:6.0f} 猫高={b['cat_h']:4d}")
    if feets:
        print(f"  -> 脚底y范围 {min(feets)}~{max(feets)} (差 {max(feets)-min(feets)}px) | 中心x范围 {min(cxs):.0f}~{max(cxs):.0f}")

for g in ["idle_open", "idle_blink", "walk", "sleep", "stretch", "wake", "groom",
          "click_surprise", "click_happy"]:
    report(g)
