import cv2, os

VIDEO = r"D:\agent\BabyCat\生成猫咪日常动作视频.mp4"
PREVIEW = r"D:\agent\BabyCat\assets\_preview"


def inspect():
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"fps={fps:.2f} frames={n} size={w}x{h} duration={n/fps:.2f}s")
    cap.release()
    return fps, n, w, h


def extract_preview(every_sec=0.5):
    os.makedirs(PREVIEW, exist_ok=True)
    cap = cv2.VideoCapture(VIDEO)
    fps = cap.get(cv2.CAP_PROP_FPS)
    step = max(1, int(fps * every_sec))
    i = 0
    saved = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if i % step == 0:
            p = os.path.join(PREVIEW, f"prev_{saved:03d}.jpg")
            cv2.imwrite(p, frame)
            saved += 1
        i += 1
    cap.release()
    print(f"saved {saved} preview frames to {PREVIEW}")


if __name__ == "__main__":
    inspect()
    extract_preview(0.5)
