import cv2
from pathlib import Path
from PIL import Image
from rembg import remove
from rembg.session_factory import new_session

VIDEO = r"D:\agent\BabyCat\生成猫咪日常动作视频.mp4"
OUT = Path(r"D:\agent\BabyCat\assets\sprites")

# 6 段自然连续动作（首尾相接、无缝衔接；时码单位：秒）
# 0-2.5 蜷睡 -> 2.5-5.5 哈欠+起身+伸懒腰 -> 5.5-8.0 转圈走动
# -> 8-10 蹲下坐好张望 -> 10-13 舔爪洗脸 -> 13-15 蜷回睡觉
# 上版 0.1-0.2s 端点内缩丢掉了过渡帧（如哈欠/起身），且漏抽 walk_circle/settle 两段
ACTIONS = {
    "sleep":       (0.0,   2.5,   20),  # 蜷缩睡觉
    "stretch":     (2.5,   5.5,   20),  # 打哈欠 + 起身 + 伸懒腰
    "walk_circle": (5.5,   8.0,   20),  # 转圈走动（填补"伸懒腰→坐下"空档）
    "wake":        (8.0,   10.0,  20),  # 蹲下 + 坐好张望
    "groom":       (10.0,  13.0,  20),  # 坐下抬爪洗脸
    "settle":      (13.0,  15.04, 20),  # 蜷回睡觉（与 sleep 衔接形成闭环）
}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    session = new_session("u2netp")
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    for name, (s0, s1, count) in ACTIONS.items():
        f0 = int(round(s0 * fps))
        f1 = int(round(s1 * fps))
        f1 = min(f1, n_total - 1)
        if f1 <= f0:
            print(f"[warn] {name}: invalid range {f0}-{f1}, skip")
            continue

        # 等距取帧（含首尾）
        if count == 1:
            indices = [f0]
        else:
            indices = [int(round(f0 + (f1 - f0) * i / (count - 1))) for i in range(count)]

        print(f"{name}: video {s0:.1f}s-{s1:.1f}s -> frames {f0}-{f1}, pick {indices}")
        for i, idx in enumerate(indices):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret:
                print(f"  [err] failed to read frame {idx}")
                continue
            # OpenCV 读入是 BGR，转成 RGB 给 rembg
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            src = Image.fromarray(rgb)
            dst = remove(src, session=session)
            out_path = OUT / f"{name}_{i+1:02d}.png"
            dst.save(out_path)
            print(f"  saved {out_path.name}")

    cap.release()
    print("\nAll done. Sprites in", OUT)

if __name__ == "__main__":
    main()