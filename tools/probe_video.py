# -*- coding: utf-8 -*-
"""视频元数据探查：打印 fps/帧数/时长，并可把 左右移动.mp4 的等间隔帧
拼成一张接触表 PNG（供人工确认动作内容与剪辑区间）。"""
import sys
from pathlib import Path

import cv2
from PIL import Image

ROOT = Path(__file__).parent.parent


def probe(path: Path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        print(f"[err] 无法打开 {path.name}")
        return None
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    dur = n / fps if fps else 0
    print(f"{path.name}: {w}x{h} fps={fps:.3f} frames={n} duration={dur:.2f}s")
    cap.release()
    return {"fps": fps, "frames": n, "w": w, "h": h}


def contact_sheet(path: Path, out_png: Path, cols=4, rows=4):
    """把视频首尾区间等间隔取 cols*rows 帧，缩略拼图输出"""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if n <= 0:
        print("  空视频")
        return
    idxs = [int(round(i * (n - 1) / (cols * rows - 1))) for i in range(cols * rows)]
    thumbs = []
    for idx in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            thumbs.append(Image.new("RGB", (180, 180), (30, 30, 30)))
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        im = Image.fromarray(rgb).resize((180, 180), Image.Resampling.LANCZOS)
        thumbs.append(im)
    sheet = Image.new("RGB", (cols * 180, rows * 180), (20, 20, 20))
    for i, t in enumerate(thumbs):
        sheet.paste(t, ((i % cols) * 180, (i // cols) * 180))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_png)
    print(f"  接触表已保存: {out_png}")


if __name__ == "__main__":
    files = [ROOT / "左右移动.mp4", ROOT / "recoil，spin.mp4", ROOT / "生成猫咪日常动作视频.mp4"]
    for f in files:
        info = probe(f)
    if len(sys.argv) > 1 and sys.argv[1] == "--sheet":
        contact_sheet(ROOT / "左右移动.mp4", ROOT / ".probe" / "walk_sheet.png", 4, 4)
        contact_sheet(ROOT / "recoil，spin.mp4", ROOT / ".probe" / "spin_sheet.png", 4, 4)
