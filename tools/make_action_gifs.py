# -*- coding: utf-8 -*-
"""视频 → 透明背景 GIF 管线。

用法:
  python make_action_gifs.py test     # 每个视频只处理首帧，输出检查图
  python make_action_gifs.py full     # 全量处理并生成 GIF

流程: ffmpeg 抽帧(15fps) → [eat] OpenCV 修补豆包水印 → rembg(isnet) 抠图
      → alpha 清理 → 按 bbox 裁剪 → 缩放 → Pillow 合成透明 GIF
"""
import os
import subprocess
import sys

import numpy as np
from PIL import Image
from rembg import remove, new_session

FF = r"C:/Users/潘锦延/.workbuddy/binaries/python/envs/default/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
ROOT = r"D:/agent/agent/BabyCat/assets"
RAW = os.path.join(ROOT, "videos_raw")
WORK = os.path.join(ROOT, "gif_work")
OUT = os.path.join(ROOT, "gifs")

FPS = 15                 # GIF 帧率
TARGET_H = 260           # 成品 GIF 猫高
SPRITE_H = 512           # 软件精灵帧高度（与既有 512 素材一致）
SPRITES_DIR = os.path.join(ROOT, "sprites")
WM_BOX = (600, 1188, 700, 1234)   # eat.mp4 豆包水印外接框(含余量)

ACTIONS = ("eat", "drink", "play", "hiss")

_session = None
_session_birefnet = None


def get_session():
    global _session
    if _session is None:
        _session = new_session("isnet-general-use")
    return _session


def get_birefnet_session():
    """isnet 抠丢时的兜底模型（白猫贴浅色地板/运动模糊帧明显更强）。"""
    global _session_birefnet
    if _session_birefnet is None:
        _session_birefnet = new_session("birefnet-general")
    return _session_birefnet


def extract_frames(action, fps=FPS):
    """抽帧为 PIL RGBA 列表（原始分辨率）。"""
    import io
    src = os.path.join(RAW, f"{action}.mp4")
    p = subprocess.run(
        [FF, "-i", src, "-vf", f"fps={fps}", "-f", "image2pipe", "-vcodec", "png", "-"],
        capture_output=True)
    if not p.stdout:
        raise RuntimeError(f"抽帧失败 {src}: {p.stderr[-300:]}")
    # PNG 流拆帧
    frames, buf, sig = [], b"", b"\x89PNG\r\n\x1a\n"
    data = p.stdout
    starts = []
    i = 0
    while True:
        j = data.find(sig, i)
        if j < 0:
            break
        starts.append(j)
        i = j + 1
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(data)
        img = Image.open(io.BytesIO(data[s:e])).convert("RGB")
        frames.append(img)
    return frames


def inpaint_watermark(frame):
    """修补 eat 帧右下角的豆包水印（静态位置）。"""
    import cv2
    x1, y1, x2, y2 = WM_BOX
    arr = np.array(frame)
    mask = np.zeros(arr.shape[:2], np.uint8)
    mask[y1:y2, x1:x2] = 255
    fixed = cv2.inpaint(arr[:, :, ::-1], mask, 5, cv2.INPAINT_TELEA)[:, :, ::-1]
    return Image.fromarray(fixed)


def clean_alpha(rgba):
    """GIF 只有二值透明：alpha 阈值化 + 侵蚀 1px + 滤掉 <30px 碎屑。"""
    import cv2
    arr = np.array(rgba)
    a = arr[..., 3]
    binary = ((a > 110) * 255).astype(np.uint8)
    binary = cv2.erode(binary, np.ones((3, 3), np.uint8), iterations=1)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    for i in range(1, n):
        if stats[i, 4] < 30:                    # 小于 30px 的孤立碎屑丢弃
            binary[labels == i] = 0
    arr[..., 3] = binary
    return Image.fromarray(arr)


def coverage(rgba):
    a = np.array(rgba.getchannel("A"))
    return (a > 110).mean() * 100


def mat_frames(action, frames):
    out = []
    fallback_n = 0
    for i, f in enumerate(frames):
        if action == "eat":
            f = inpaint_watermark(f)
        m = remove(f, session=get_session(), post_process_mask=True)
        # isnet 偶尔整帧抠丢（覆盖率异常低）→ 换 birefnet 兜底
        if coverage(m) < 25:
            m2 = remove(f, session=get_birefnet_session(), post_process_mask=True)
            if coverage(m2) > coverage(m):
                m = m2
                fallback_n += 1
        out.append(clean_alpha(m))
    if fallback_n:
        print(f"[{action}] {fallback_n} 帧用 birefnet 兜底重抠")
    return out


def content_box(frames, pad=6):
    """所有帧不透明区域的并集 bbox，保证 GIF 里猫不跳尺寸。"""
    x1 = y1 = 10 ** 9
    x2 = y2 = -1
    for f in frames:
        a = np.array(f.getchannel("A"))
        ys, xs = np.where(a > 60)
        if not len(ys):
            continue
        x1, y1 = min(x1, xs.min()), min(y1, ys.min())
        x2, y2 = max(x2, xs.max()), max(y2, ys.max())
    x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
    x2 = min(frames[0].width - 1, x2 + pad)
    y2 = min(frames[0].height - 1, y2 + pad)
    return (x1, y1, x2, y2)


def build_gif(action, frames, out_path):
    box = content_box(frames)
    w = box[2] - box[0] + 1
    h = box[3] - box[1] + 1
    scale = TARGET_H / h
    tw = max(1, round(w * scale))
    seq = []
    for f in frames:
        c = f.crop(box)
        c = c.resize((tw, TARGET_H), Image.LANCZOS)
        seq.append(c)
    seq[0].save(
        out_path, save_all=True, append_images=seq[1:],
        duration=round(1000 / FPS), loop=0, disposal=2, optimize=True)
    return len(seq), (tw, TARGET_H)


def make_check(action, frames_matted, path):
    """抠图结果合成绿色背景 + 放大右下角，供视觉检查。"""
    f = frames_matted[0]
    bg = Image.new("RGB", f.size, (80, 200, 120))
    bg.paste(f, (0, 0), f)
    crop = bg.crop((f.width // 2, f.height - 360, f.width, f.height))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.LANCZOS)
    crop.save(path, quality=90)


def export_sprites(action, frames, target_h=SPRITE_H):
    """抠好的帧裁剪并导出为 assets/sprites/{action}_NN.png（软件动作序列用）。"""
    box = content_box(frames)
    w = box[2] - box[0] + 1
    h = box[3] - box[1] + 1
    scale = target_h / h
    tw = max(1, round(w * scale))
    for i, f in enumerate(frames, 1):
        c = f.crop(box).resize((tw, target_h), Image.LANCZOS)
        c.save(os.path.join(SPRITES_DIR, f"{action}_{i:02d}.png"))
    return len(frames)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    only = sys.argv[2] if len(sys.argv) > 2 else None   # 只处理指定动作
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)
    for action in ACTIONS:
        if only and action != only:
            continue
        frames = extract_frames(action)
        print(f"[{action}] 抽帧 {len(frames)} 张")
        frames = frames[:1] if mode == "test" else frames
        matted = mat_frames(action, frames)
        make_check(action, matted, os.path.join(WORK, f"check_{action}.jpg"))
        if mode == "full":
            n, size = build_gif(action, matted, os.path.join(OUT, f"{action}.gif"))
            kb = os.path.getsize(os.path.join(OUT, f"{action}.gif")) // 1024
            print(f"[{action}] GIF 完成: {n} 帧, {size[0]}x{size[1]}, {kb} KB")
        elif mode == "sprites":
            n = export_sprites(action, matted)
            print(f"[{action}] 精灵帧导出: {n} 张 @ {SPRITE_H}px")
    print("done")


if __name__ == "__main__":
    main()
