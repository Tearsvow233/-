"""生成视频接触表（contact sheet），用于目视划定动作分段边界。
用法: python tools/make_contact_sheet.py [视频路径] [列数] [行数]
输出: tools/_contact_sheet.png
"""
import sys
from pathlib import Path
import cv2
from PIL import Image, ImageDraw

DEFAULT_VIDEO = r"D:\agent\BabyCat\生成猫咪日常动作视频.mp4"
OUT = Path(r"D:\agent\BabyCat\tools\_contact_sheet.png")


def main():
    video = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_VIDEO
    cols = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    rows = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    cell = 200
    pad_top = 18

    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    dur = n_total / fps
    total = cols * rows

    print(f"video fps={fps} frames={n_total} duration={dur:.2f}s -> sample {total} frames")

    sheet = Image.new("RGB", (cols * cell, rows * (cell + pad_top)), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)

    for i in range(total):
        # 等距采样（含首尾）
        idx = int(round((n_total - 1) * i / (total - 1))) if total > 1 else 0
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((cell, cell), Image.LANCZOS)

        r, c = divmod(i, cols)
        x, y = c * cell, r * (cell + pad_top)
        sheet.paste(img, (x, y + pad_top))
        t = idx / fps
        label = f"#{i:02d} f{idx:03d} {t:.2f}s"
        draw.text((x + 3, y + 3), label, fill=(20, 20, 20))

    cap.release()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT)
    print("saved ->", OUT)


if __name__ == "__main__":
    main()
