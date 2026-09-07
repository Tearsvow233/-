# -*- coding: utf-8 -*-
"""L3 端到端验证：L2 失败样本 -> 真实免费 API (glm-4-flash-250414) -> 入库 dict
用法: python tools/test_l3_e2e.py [settings.json 路径]
"""
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ai_chat import PetAI                       # noqa: E402
from reminder_parser import parse_reminder, describe as describe_reminder  # noqa: E402


def load_settings(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    s = load_settings(sys.argv[1] if len(sys.argv) > 1 else "settings.json")
    ai = PetAI(s)
    print(f"model={s.get('ai_model')} base={s.get('ai_base_url')} enabled={s.get('ai_enabled')}")
    print("=" * 70)
    cases = [
        "每周一晚上8点提醒开会",          # weekly 20:00
        "明天早上9点提醒交作业",          # 一次性 -> 明天9点
        "25分钟后提醒我喝水",            # interval 25 一次性
        "每30分钟提醒我喝水",            # interval 30 循环
        "今晚11点提醒睡觉",              # 一次性 -> 今晚23点
        "下周三下午2点提醒我去医院",       # 一次性 -> 下周三14点
        "每天下午3点提醒我吃水果",         # daily 15:00
    ]
    for text in cases:
        print(f"\n■ 输入: {text}")
        # ---- L2 先试（模拟真实链路）----
        r2 = parse_reminder(text)
        if r2:
            print(f"  [L2] 命中: {json.dumps(r2, ensure_ascii=False)}")
            print(f"        → {describe_reminder(r2)}")
            continue
        print(f"  [L2] 未命中 → 走 L3 LLM 解析")
        r3 = ai.parse_reminder_spec(text)
        if r3:
            print(f"  [L3] OK: {json.dumps(r3, ensure_ascii=False)}")
            print(f"        → {describe_reminder(r3)}")
        else:
            print(f"  [L3] FAILED (None)")


if __name__ == "__main__":
    main()
