# -*- coding: utf-8 -*-
"""AI 连通性自检工具：读 settings.json -> POST /chat/completions -> 打印结果。

用法：
    python tools/test_ai_link.py [settings.json 路径]
    默认读根目录 settings.json；也可传 dist/settings.json 验证 exe 那份。
用途：
    充值后 / 换模型后 一键确认 key+端点+模型 是否真的能用。
"""
import json
import sys
import urllib.request
import urllib.error

path = sys.argv[1] if len(sys.argv) > 1 else "settings.json"
with open(path, encoding="utf-8") as f:
    s = json.load(f)

base = (s.get("ai_base_url") or "").rstrip("/")
key = (s.get("ai_api_key") or "").strip()
model = s.get("ai_model") or ""
enabled = s.get("ai_enabled", False)
print(f"配置文件: {path}")
print(f"enabled={enabled}  model={model}")
print(f"base_url={base}")
print(f"key={'已填(' + key[:8] + '...' + key[-4:] + ')' if key else '空'}")

if not (enabled and key):
    print(">>> 未启用或无 key，跳过联网测试")
    sys.exit(0)

payload = {
    "model": model,
    "messages": [{"role": "user", "content": "你好，只回两个字：在的"}],
    "temperature": 0.5,
    "max_tokens": 10,
}
req = urllib.request.Request(base + "/chat/completions",
                             data=json.dumps(payload).encode("utf-8"), method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("Authorization", "Bearer " + key)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        obj = json.loads(resp.read().decode("utf-8"))
    content = obj["choices"][0]["message"]["content"].strip()
    print(f">>> 连接成功！AI 回复：{content}")
except urllib.error.HTTPError as e:
    body = e.read().decode("utf-8", "replace")[:300]
    print(f">>> HTTP {e.code}：{body}")
    if e.code == 429 and "1113" in body:
        print("    提示：当前 model 是付费档但账户没余额。")
        print("    可改用免费模型 glm-4.7-flash（智谱永久免费档），或去 open.bigmodel.cn 充值。")
except Exception as e:
    print(f">>> 失败：{e}")
