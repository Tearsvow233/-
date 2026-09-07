# -*- coding: utf-8 -*-
"""
BabyCat 新动作素材处理：recoil / spin / 左右移动(pace)
- 读入视频，按时间段剪切
- rembg u2netp 自动抠除背景
- 输出到 assets/sprites/{name}_{i:02d}.png
"""
import cv2
from pathlib import Path
from PIL import Image
from rembg import remove
from rembg.session_factory import new_session

ROOT = Path(__file__).parent.parent
OUT = ROOT / "assets" / "sprites"
OUT.mkdir(parents=True, exist_ok=True)

# ---- 剪切配置 ----
# recoil：被点击后的后仰/站起反应（短促）
# spin：抬手歪头转圈（较长）
# pace：左右移动踱步（循环感）
# 三个动作的素材视频均为 24fps，本次按原速 24fps 提取区间内每一帧，
# 解决低 fps 抽帧导致的卡顿。fps=24 表示"逐帧取，播放时原速"。
ACTION_CLIPS = {
    "recoil": {
        "video": ROOT / "recoil，spin.mp4",
        "start": 0.0,
        "end": 2.5,
        "fps": 24,    # 0~2.5s * 24fps = 60 帧
    },
    "spin": {
        "video": ROOT / "recoil，spin.mp4",
        "start": 2.5,
        "end": 7.5,
        "fps": 24,    # 2.5~7.5s * 24fps = 120 帧
    },
    "pace": {
        "video": ROOT / "左右移动.mp4",
        "start": 0.0,
        "end": 8.0,
        "fps": 24,    # 0~8.0s * 24fps = 192 帧
    },
}


def extract_clip(name, cfg, session):
    video = str(cfg["video"])
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        print(f"[err] 无法打开视频: {video}")
        return 0

    vfps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    s0, s1 = cfg["start"], cfg["end"]
    f0 = int(round(s0 * vfps))
    f1 = min(int(round(s1 * vfps)), n_total - 1)
    target_fps = float(cfg.get("fps") or vfps)

    if f1 <= f0:
        print(f"[warn] {name}: 无效区间 {f0}-{f1}，跳过")
        cap.release()
        return 0

    # 目标 fps >= 视频 fps：把 [s0,s1) 内的视频帧逐帧取全（24fps 原速，无抽帧损耗）
    # 否则：按目标 fps 在区间内均匀取样
    if target_fps >= vfps - 1e-6:
        indices = list(range(f0, f1))
    else:
        count = max(1, int(round((s1 - s0) * target_fps)))
        if count == 1:
            indices = [f0]
        else:
            indices = [int(round(f0 + (f1 - 1 - f0) * i / (count - 1)))
                       for i in range(count)]

    print(f"{name}: {Path(video).name if isinstance(video, Path) else video} "
          f"{s0:.2f}s-{s1:.2f}s -> 帧 {f0}-{f1}，抽 {len(indices)} 帧 "
          f"(视频 {vfps:.0f}fps / 目标 {target_fps:.0f}fps)")

    saved = 0
    total = len(indices)
    for i, idx in enumerate(indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = cap.read()
        if not ret:
            print(f"  [err] {name}: 读取帧 {idx} 失败")
            continue
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        src = Image.fromarray(rgb)
        dst = remove(src, session=session)
        # 保持 720x720 透明画布；如需与旧素材一致可取消注释下方 upscale
        # dst = dst.resize((1024, 1024), Image.Resampling.LANCZOS)
        out_path = OUT / f"{name}_{i+1:02d}.png"
        dst.save(out_path)
        saved += 1
        if (i + 1) % 24 == 0 or i == total - 1:
            print(f"  [{i+1}/{total}] {out_path.name}")

    cap.release()
    return saved


def main():
    print("正在创建 rembg u2netp session（首次约 5-10s）...")
    session = new_session("u2netp")
    print("Session OK:", session.model_name)

    total = 0
    for name, cfg in ACTION_CLIPS.items():
        total += extract_clip(name, cfg, session)

    print(f"\n完成，共生成 {total} 帧，目录: {OUT}")


if __name__ == "__main__":
    main()
