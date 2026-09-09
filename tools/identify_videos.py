# -*- coding: utf-8 -*-
"""抽取 4 个视频的中间帧并用 GLM 视觉模型识别动作（哈气/吃饭/喝水/玩耍）。"""
import base64, io, json, subprocess, sys, urllib.request

FF = r"C:/Users/潘锦延/.workbuddy/binaries/python/envs/default/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg-win-x86_64-v7.1.exe"
VIDEOS = [
    ("hiss", r"D:/agent/微信视频2026-09-09_182837_263.mp4"),
    ("eat", r"D:/agent/微信视频2026-09-09_182851_311.mp4"),
    ("drink", r"D:/agent/微信视频2026-09-09_182855_878.mp4"),
    ("play", r"D:/agent/微信视频2026-09-09_183008_043.mp4"),
]

def mid_frame_b64(path):
    """抽中间帧 → 缩到宽 360 的 JPEG base64。"""
    out = subprocess.run([FF, "-i", path], capture_output=True, text=True, encoding="utf-8", errors="replace")
    dur = 0.0
    for line in out.stderr.splitlines():
        if "Duration" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
    t = dur / 2
    p = subprocess.run([FF, "-ss", str(t), "-i", path, "-frames:v", "1",
                        "-vf", "scale=360:-2", "-q:v", "5", "-f", "image2pipe", "-vcodec", "mjpeg", "-"],
                       capture_output=True)
    if not p.stdout:
        raise RuntimeError(f"抽帧失败 {path}: {p.stderr[:300]}")
    return base64.b64encode(p.stdout).decode()

cfg = json.load(open(r"D:/agent/agent/BabyCat/settings.json", encoding="utf-8"))
for tag, path in VIDEOS:
    b64 = mid_frame_b64(path)
    payload = {
        "model": "glm-4v-flash",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "这个视频画面里的猫在做什么动作？从以下四个选项中选一个，只回答两三个字：哈气 / 吃饭 / 喝水 / 玩耍。如果都不是，简单描述动作。"},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
        "temperature": 0.1, "max_tokens": 50,
    }
    req = urllib.request.Request(cfg["ai_base_url"] + "/chat/completions",
                                 data=json.dumps(payload).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {cfg['ai_api_key']}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            obj = json.loads(r.read().decode())
        print(tag, "->", obj["choices"][0]["message"]["content"].strip())
    except Exception as e:
        print(tag, "-> ERROR", e)
