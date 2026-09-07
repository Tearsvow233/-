"""把所有精灵图归一化到统一画布：猫水平居中、脚底对齐同一条基线，保留各自自然大小。
这样切换 idle/动作/散步时不会左右/上下跳位。先自动备份到 assets/sprites_backup/，可随时还原。"""
from pathlib import Path
from PIL import Image
import shutil, glob

SPRITES = Path(r"D:\agent\BabyCat\assets\sprites")
BACKUP = Path(r"D:\agent\BabyCat\assets\sprites_backup")
S = 1024            # 统一画布边长（足够容纳最高的猫，不放大模糊）
FEET_Y = S - 20     # 脚底基线（距顶 FEET_Y 像素）
CENTER_X = S // 2   # 水平中心
ALPHA_MIN = 20

def bbox(im):
    w, h = im.size
    px = im.load()
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > ALPHA_MIN:
                if x < minx: minx = x
                if x > maxx: maxx = x
                if y < miny: miny = y
                if y > maxy: maxy = y
    if maxx < 0:
        return None
    return (minx, miny, maxx, maxy)

def main():
    BACKUP.mkdir(parents=True, exist_ok=True)
    files = sorted(glob.glob(str(SPRITES / "*.png")))
    for f in files:
        p = Path(f)
        # 首次运行才备份（备份里已有则跳过）
        bk = BACKUP / p.name
        if not bk.exists():
            shutil.copy(p, bk)
        im = Image.open(p).convert("RGBA")
        b = bbox(im)
        if b is None:
            print(f"  [skip] {p.name}: 全透明"); continue
        l, t, r, bb = b
        cat_w, cat_h = r - l, bb - t
        canvas = Image.new("RGBA", (S, S), (0,0,0,0))
        crop = im.crop((l, t, r+1, bb+1))
        tx = CENTER_X - cat_w // 2
        ty = FEET_Y - cat_h
        if ty < 0:
            ty = 0  # 极端情况保护，避免裁顶
        canvas.paste(crop, (tx, ty), crop)
        canvas.save(p)
        print(f"  norm {p.name:20s} w={cat_w:4d} h={cat_h:4d} -> x={tx} y={ty}")
    print(f"\n完成。已归一化 {len(files)} 张；原图备份在 {BACKUP}")

if __name__ == "__main__":
    main()
