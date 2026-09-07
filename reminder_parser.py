# -*- coding: utf-8 -*-
"""本地 NLP-lite 提醒解析器（L2，零 API 成本）。

把一句自然语言解析成提醒任务，失败返回 None（交给 L3 或提示用户换说法）。

设计边界（重要）：
- 只处理有十足把握的简单句；一旦出现 L2 无法精确计算的语义
  （每周X、明天/今晚/下周X 等一次性时刻）→ 一律返回 None，把解析权交给 L3
  （LLM 免费兜底），避免"半懂装懂"生成错误提醒。
  判断标准：宁可不解析（走 L3 / 提示用户），也不错解析（生成错误提醒）。

支持示例：
  "3分钟后提醒我喝水"        -> 一次性，3 分钟后
  "1小时后提醒开会"          -> 一次性，60 分钟后
  "半小时后提醒我休息"       -> 一次性，30 分钟后
  "2小时30分钟后提醒吃水果"  -> 一次性，150 分钟后（累加）
  "每天9点提醒吃药"          -> 每天 09:00
  "每天下午3点提醒我喝水"    -> 每天 15:00
  "15:30 提醒接孩子"         -> 每天 15:30
  "每天早上8点跑步"          -> 每天 08:00

明确不支持（返回 None → L3 / 用户换说法）：
  "每周一晚上8点提醒开会"    （weekly 语义 → L3）
  "明天早上9点提醒交作业"    （一次性日期 → L3）
  "今晚11点提醒睡觉"         （一次性时刻 → L3）

返回 dict：
  {"name": str, "mode": "interval"|"daily", "interval_min": int,
   "at": "HH:MM"|None, "once": bool, "enabled": True}
"""
import re

CN_DIGITS = {
    '零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9,
}

# 每周/每个星期/礼拜X → weekly 语义（L2 不解析，交 L3）
_WEEKLY_HINTS = re.compile(
    r'(每周|每星期|每个星期|每个周|礼拜[一二三四五六日天])')
# 一次性日期/时刻词 → L2 无法精确换算，交 L3
_ONCE_HINTS = re.compile(
    r'(明天|明早|明晚|明儿|今天|今早|今晚|今夜|后天|大后天|'
    r'下周|下个?星期|下礼拜|这周|这星期|本周|这个?星期|这礼拜|'
    r'凌晨\d|明晚\d|今晚\d|明天\d)')


def _cn2int(s):
    """中文/阿拉伯数字 -> int。支持 十 / 十五 / 二十 / 三十五"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s in CN_DIGITS:
        return CN_DIGITS[s]
    if '十' in s:
        parts = s.split('十')
        tens = CN_DIGITS.get(parts[0], 1) if parts[0] else 1
        ones = CN_DIGITS.get(parts[1], 0) if len(parts) > 1 and parts[1] else 0
        return tens * 10 + ones
    return None


def _extract_clock(text):
    """提取时刻 -> (hh, mm) 或 None。支持 9点 / 9:30 / 下午3点 / 15:30"""
    m = re.search(r'(\d{1,2})\s*[::]\s*(\d{2})', text)     # 15:30 / 9:05
    if m:
        hh, mm = int(m.group(1)), int(m.group(2))
    else:
        m = re.search(r'(\d{1,2})\s*[点點時时]', text)
        if not m:
            return None
        hh, mm = int(m.group(1)), 0
    # 上下午/早晚 换算
    if re.search(r'(下午|晚上|傍晚|夜里|深夜)', text):
        if hh < 12:
            hh += 12
    elif re.search(r'(上午|早上|早晨|凌晨)', text):
        if hh == 12:
            hh = 0
    return (hh % 24, mm % 60)


def _extract_content(text):
    """剥掉时间描述和"提醒"等动词，剩下的即提醒内容"""
    s = text
    s = re.sub(r'(提醒|叫|喊|提示|通知)\s*(我|一下|一声|一下我)?', ' ', s)
    # 剥"每天/每晚/每早 + 时段前缀"整块（不吞正文，如"每天早上8点跑步"→跑步）
    s = re.sub(
        r'每[天日早晚周]\s*(\d{1,2}\s*[点點時时]|\d{1,2}\s*[:：]\s*\d{1,2}|'
        r'[上午中午下午晚上凌晨傍晚夜里深夜早晨早上]+)?', ' ', s)
    s = re.sub(r'(上午|中午|下午|晚上|凌晨|傍晚|夜里|深夜)', ' ', s)
    s = re.sub(r'\d{1,2}\s*[::]\s*\d{2}', ' ', s)
    s = re.sub(r'\d{1,2}\s*[点點時时]', ' ', s)
    # 连同前导的"每/每隔"一起剥掉（修"每30分钟"残留"每"字）
    s = re.sub(r'(每|每隔)\s*[半\d一二三四五六七八九十两]+\s*'
               r'(分钟|分|秒钟?|个?小时|钟头|半天|天)', ' ', s)
    s = re.sub(r'[半\d一二三四五六七八九十两]+\s*(分钟|分|秒钟?|个?小时|钟头|半天|天)', ' ', s)
    s = re.sub(r'(之后|以后|后|到时候|到时)', ' ', s)
    s = re.sub(r'[的在\s，,。、！!？?~～]+', '', s)
    return s.strip()


def parse_reminder(text):
    """解析一句自然语言 -> 提醒 dict，或 None（解析失败 / 明确交 L3）"""
    t = (text or "").strip()
    if not t:
        return None

    # ---- 0) L2 边界：没十足把握的语义直接失败（交 L3 LLM 解析）----
    if _WEEKLY_HINTS.search(t):
        return None          # 每周X / 礼拜X → weekly，L2 不支持
    if _ONCE_HINTS.search(t):
        # 明天9点 / 今晚11点 / 下周三 等一次性绝对时刻 → 交 L3
        # 但"明天9点"后面若还有 每N分钟 前缀（如"从明天开始每30分钟"）——
        # 这类混合句太复杂，同样交 L3，这里统一放行 None
        return None

    is_recurring = bool(re.search(r'每[天日早晚]', t))   # 每天/每晚/每早（不含每周）
    content = _extract_content(t)

    # ---- A) 每天/每早/每晚 HH:MM ----
    if is_recurring:
        clock = _extract_clock(t)
        if clock:
            hh, mm = clock
            return {
                "name": content or "提醒",
                "mode": "daily",
                "at": f"{hh:02d}:{mm:02d}",
                "interval_min": 0,
                "once": False,
                "enabled": True,
            }

    # ---- A2) 每N分钟 / 每隔N分钟（循环 interval，once=False）----
    rep = re.search(
        r'(每|每隔)\s*([半\d一二三四五六七八九十两]+)\s*'
        r'(分钟|分|个?小时|钟头)', t)
    if rep:
        num_s, unit = rep.group(2), rep.group(3)
        if num_s == '半':
            n = 30 if ('小时' in unit or '钟头' in unit) else 1
        else:
            n = _cn2int(num_s) or 0
        if n > 0:
            mins = n * 60 if ('小时' in unit or '钟头' in unit) else n
            return {
                "name": content or "提醒",
                "mode": "interval",
                "interval_min": max(1, int(mins)),
                "once": False,
                "enabled": True,
            }

    # ---- B) N 分钟/小时/天后（一次性，可累加多个单位如 "2小时30分钟"）----
    units = re.findall(r'([半\d一二三四五六七八九十两]+)\s*(秒钟?|分钟|分|个?小时|钟头|半天|天)', t)
    if units and not is_recurring:
        mins_total = 0
        for num_s, unit in units:
            if num_s == '半':
                # 半小时 = 30 min；半天 = 720 min（不参与小时相乘）
                if '天' in unit:
                    m = 720
                else:
                    m = 30
            else:
                n = _cn2int(num_s)
                if n is None:
                    continue
                if '小时' in unit or '钟头' in unit:
                    m = n * 60
                elif '天' in unit:
                    m = n * 1440
                elif '秒' in unit:
                    m = 1 if n < 60 else n // 60
                else:
                    m = n
            mins_total += m
        if mins_total > 0:
            return {
                "name": content or "提醒",
                "mode": "interval",   # 一次性也用定时器实现，触发后自动停用
                "interval_min": max(1, int(mins_total)),
                "once": True,
                "enabled": True,
            }

    # ---- C) 裸时刻 "15:30 接孩子"（默认按每天）----
    clock = _extract_clock(t)
    if clock and not re.search(r'[分秒天]|小时|钟头', t):
        hh, mm = clock
        return {
            "name": content or "提醒",
            "mode": "daily",
            "at": f"{hh:02d}:{mm:02d}",
            "interval_min": 0,
            "once": False,
            "enabled": True,
        }

    return None


def describe(r):
    """把提醒 dict 说成人话，用于气泡/列表确认"""
    if not r:
        return ""
    name = r.get("name", "提醒")
    if r.get("mode") == "daily":
        return f"每天 {r.get('at', '09:00')} · {name}"
    if r.get("mode") == "weekly":
        wd = r.get("weekday")
        try:
            cn = "一二三四五六日"[int(wd) - 1] if wd else "?"
        except Exception:
            cn = "?"
        return f"每周{cn} {r.get('at', '09:00')} · {name}"
    if r.get("once"):
        # 有绝对时刻（L3 算出来的）优先显示时刻，否则显示倒计时分钟
        if r.get("at_text"):
            return f"{r.get('at_text')} · {name}（一次性）"
        return f"{r.get('interval_min', 0)} 分钟后 · {name}（一次性）"
    return f"每 {r.get('interval_min', 0)} 分钟 · {name}"
