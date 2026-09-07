# -*- coding: utf-8 -*-
"""小江的 AI 对话模块（OpenAI 兼容接口，纯标准库 urllib，零额外依赖）。

设计原则：
- 未启用 / 没填 key / 调用失败 时一律返回 None，由调用方回退到内置 canned 文案，
  保证程序永远不会因为"没配 AI"而报错或卡住。
- base_url / model / persona 都可配置，既能接官方 OpenAI，也能接本地或第三方兼容服务。
"""
import json
import re
import urllib.request
import urllib.error
from datetime import datetime, timedelta

# 原句中"一次性时刻"指示词（用于修正 LLM 把下周X误判成每周X）
_ONCE_HINTS = re.compile(r"(下|这|本)\s*周|明天|明早|明晚|今晚|今早|今天|后天|大后天|凌晨")
# 原句明确"每 N 分钟"循环
_REPEAT_MINS = re.compile(r"(每|每隔)\s*\d+\s*(分钟|分|小时|钟头)")


class PetAI:
    def __init__(self, settings):
        self.settings = settings

    def _cfg(self):
        s = self.settings
        return dict(
            enabled=s.get("ai_enabled", False),
            key=(s.get("ai_api_key", "") or "").strip(),
            base=(s.get("ai_base_url", "https://api.openai.com/v1") or "").rstrip("/"),
            model=s.get("ai_model", "gpt-4o-mini"),
            persona=s.get("ai_persona",
                "你是一只叫小江的布偶猫桌面宠物，可爱、有点傲娇、爱撒娇。"
                "用中文简短回复，不超过30字，可以带点语气词。"),
        )

    @staticmethod
    def _time_context():
        """生成当前时间上下文字符串，注入 system prompt 让 AI 不要说错时段"""
        now = datetime.now()
        wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        return (
            f"现在是{now.month}月{now.day}日{wd} {now.hour:02d}:{now.minute:02d}。"
            "注意：问候语、语气要符合当下时段，不要在上午/下午说晚上好。"
        )

    def reply(self, user_text, history=None):
        """返回 AI 回复字符串；不可用（未启用/无key/出错）时返回 None。
        history: 可选多轮上下文 [{"role":"user"/"assistant","content":...}]，让小江接住上下文。"""
        c = self._cfg()
        if not c["enabled"] or not c["key"]:
            return None
        messages = [{"role": "system", "content": c["persona"] + " " + self._time_context()}]
        if history:
            for h in history[-12:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    messages.append({"role": h["role"], "content": h["content"]})
        messages.append({"role": "user", "content": user_text})
        payload = {
            "model": c["model"],
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 80,
        }
        url = c["base"] + "/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {c['key']}")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            content = obj["choices"][0]["message"]["content"].strip()
            return content or None
        except Exception as e:
            # 调用方据此回退到 canned 文案
            return f"__ERR__{e}"

    # ---------- L3：把一句话解析成结构化提醒（LLM 只输出时间意图，日期差本地算）----------
    _SPEC_SYSTEM = (
        "你是提醒任务解析器。把用户的一句话解析成提醒，只输出一个 JSON 对象，"
        "不要任何解释、前后缀或代码块标记。\n"
        "今天日期 {today}，当前时间 {now}。\n"
        "输出 JSON 字段：\n"
        "name: 提醒内容，去掉时间和提醒/叫我等词（如：交作业）；\n"
        "mode: interval 或 daily 或 weekly；\n"
        "interval_min: 分钟整数，mode 为 interval 时填；\n"
        "datetime: YYYY-MM-DD HH:MM，一次性到某个具体时刻时填（mode 填 interval）；\n"
        "at: HH:MM 24小时制，daily/weekly 时填；\n"
        "weekday: 1到7整数，weekly 时填（1=周一 7=周日）；\n"
        "once: true。\n"
        "规则：\n"
        "- 只有用户明确说 N分钟后/1小时后/半小时后 这类相对时间：mode=interval，"
        "填 interval_min，datetime 留空。\n"
        "- 每N分钟/每隔N分钟：mode=interval，填 interval_min，once=false（循环）。\n"
        "- 凡是带一次性时刻词的（明天X点/今晚X点/下周X/这周五/后天/日期）："
        "一律 mode=interval + 填 datetime 为绝对时间（今天之后的最近该时刻，"
        "如 {next_day} 09:00），interval_min 填 0，once=true。"
        "你只负责给出正确日期，分钟数不用算。\n"
        "- 每天X点：mode=daily，填 at。\n"
        "- 每周一X点/每个星期三晚上8点（带每字的星期循环）：mode=weekly，填 at 和 weekday。\n"
        "- 下周三X点/这周五X点/本周一X点（下周/这周/本周 + 周几 + 一次性时刻）："
        "mode=weekly，填 weekday 和 at，datetime 留空，once=true；"
        "日期差由系统本地计算，你不要推算具体日期。\n"
        "- 实在无法判断时：mode=interval 并合理估计 interval_min。\n"
    )

    def parse_reminder_spec(self, user_text):
        """把自然语言提醒转成标准提醒 dict；失败/未启用返回 None。

        返回结构与 reminder_parser.parse_reminder 一致：
          {"name", "mode": "interval"|"daily"|"weekly", "interval_min",
           "at": "HH:MM"|None, "weekday": 1-7|None, "once": bool, "enabled": True}
        一次性具体时刻（明天9点）会换算成 interval_min 分钟数（once=True）。
        """
        c = self._cfg()
        if not c["enabled"] or not c["key"]:
            return None
        now = datetime.now()
        tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        system = self._SPEC_SYSTEM.format(
            today=now.strftime("%Y-%m-%d"), now=now.strftime("%H:%M"),
            next_day=tomorrow)
        payload = {
            "model": c["model"],
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.0,
            "max_tokens": 200,
        }
        url = c["base"] + "/chat/completions"
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {c['key']}")
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                obj = json.loads(resp.read().decode("utf-8"))
            content = obj["choices"][0]["message"]["content"].strip()
        except Exception:
            return None
        return self._normalize_spec(content, user_text)

    @staticmethod
    def _normalize_spec(content, raw_text=""):
        """解析并校验 LLM 输出的 JSON，归一化成提醒 dict；失败返回 None

        raw_text：用户原句，用于本地兜底修正 LLM 的 once/模式误判。
        """
        if not content:
            return None
        # 容错：剥掉可能的 ```json ... ``` 或首尾花括号外的杂质
        content = content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
        try:
            start = content.find("{")
            end = content.rfind("}")
            if start < 0 or end <= start:
                return None
            d = json.loads(content[start:end + 1])
        except Exception:
            return None
        name = str(d.get("name") or "提醒").strip()[:20] or "提醒"
        mode = d.get("mode") or "interval"
        base = {"name": name, "enabled": True,
                "at": None, "weekday": None, "interval_min": 0}
        raw = raw_text or ""
        # 原句含一次性指示词（下/这/本周、明天、今晚、后天等）→ 一次性语义优先
        once_hint = bool(_ONCE_HINTS.search(raw))
        # 原句明确"每N分钟"循环
        repeat_mins = bool(_REPEAT_MINS.search(raw))

        if mode == "daily":
            hh, mm = _split_hm(d.get("at"))
            if hh is None:
                return None
            # 原句是"明天/今晚X点"（一次性）→ 转成该时刻的一次性倒计时
            if once_hint:
                target = _parse_dt(datetime.now().strftime("%Y-%m-%d") + f" {hh:02d}:{mm:02d}")
                if target:
                    mins = max(1, int((target - datetime.now()).total_seconds() // 60) + 1)
                    base.update(mode="interval", interval_min=mins, once=True,
                                at_text=_fmt_target(target))
                    return base
            base.update(mode="daily", at=f"{hh:02d}:{mm:02d}")
            return base

        if mode == "weekly":
            hh, mm = _split_hm(d.get("at"))
            try:
                wd = int(d.get("weekday"))
                if not 1 <= wd <= 7:
                    return None
            except Exception:
                return None
            if hh is None:
                return None
            # 原句是"下周X/这周X"（一次性）→ 转成该周几最近的 datetime
            if once_hint:
                target = _next_weekday_at(wd, hh, mm)
                if target:
                    mins = max(1, int((target - datetime.now()).total_seconds() // 60) + 1)
                    base.update(mode="interval", interval_min=mins, once=True,
                                at_text=_fmt_target(target))
                    return base
            base.update(mode="weekly", at=f"{hh:02d}:{mm:02d}", weekday=wd)
            return base

        # ---- interval ----
        # 兜底：原句是"下周X/这周五"（含周几的一次性词），即使 LLM 错给了
        # datetime 或 mode，也一律按"最近的那个周几"本地精确重算（不信 LLM 日期）
        wd = _wd_of_raw(raw)
        if wd:
            hh, mm = _split_hm(d.get("at"))
            if hh is None and d.get("datetime"):
                hh, mm = _split_hm(str(d["datetime"])[11:16])
            if hh is not None:
                target = _next_weekday_at(wd, hh, mm)
                if target:
                    mins = max(1, int((target - datetime.now()).total_seconds() // 60) + 1)
                    base.update(mode="interval", interval_min=mins, once=True,
                                at_text=_fmt_target(target))
                    return base
        if d.get("datetime"):
            target = _parse_dt(str(d["datetime"]))
            if target:
                mins = max(1, int((target - datetime.now()).total_seconds() // 60) + 1)
                base.update(mode="interval", interval_min=mins, once=True,
                            at_text=_fmt_target(target))
                return base
        try:
            mins = max(1, int(d.get("interval_min") or 0))
        except Exception:
            return None
        # interval 的循环/一次性只按原句判断：明确"每/每隔N分钟"才是循环，其余一律一次性
        base.update(mode="interval", interval_min=mins, once=not repeat_mins)
        return base


def _split_hm(at):
    """'HH:MM' -> (hh, mm)；解析失败返回 (None, None)"""
    try:
        hh, mm = str(at).split(":")
        h, m = int(hh), int(mm)
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
    except Exception:
        pass
    return None, None


_WD_CN = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}


def _wd_of_raw(raw):
    """原句含"下周X/这周五/本周一"等一次性周几 → 返回 1..7；否则 None"""
    m = re.search(r"(下|这|本)\s*(周|星期|礼拜)\s*([一二三四五六日天])", raw or "")
    if m:
        return _WD_CN.get(m.group(3))
    m = re.search(r"(下|这|本)\s*([一二三四五六日天])\s*(周|星期|礼拜)?", raw or "")
    if m and re.search(r"(周|星期|礼拜)", raw or ""):
        return _WD_CN.get(m.group(2))
    return None


def _fmt_target(target):
    """把绝对时刻说成人话：今天/明天/后天/M月D日 + HH:MM"""
    now = datetime.now()
    days = (target.replace(hour=0, minute=0, second=0, microsecond=0)
            - now.replace(hour=0, minute=0, second=0, microsecond=0)).days
    hm = target.strftime("%H:%M")
    if days == 0:
        return f"今天 {hm}"
    if days == 1:
        return f"明天 {hm}"
    if days == 2:
        return f"后天 {hm}"
    return f"{target.month}月{target.day}日 {hm}"


def _parse_dt(s):
    """'YYYY-MM-DD HH:MM' -> datetime；过去时间自动顺延一天；非法返回 None"""
    try:
        t = datetime.strptime(str(s).strip()[:16], "%Y-%m-%d %H:%M")
    except Exception:
        return None
    now = datetime.now()
    if t < now:
        t += timedelta(days=1)   # 已过 → 顺延到明天同一时刻
    if t > now + timedelta(days=400):   # 明显异常的未来 → 判非法
        return None
    return t


def _next_weekday_at(weekday, hh, mm):
    """下一个 weekday（1=周一..7=周日）的 hh:mm 对应的 datetime"""
    now = datetime.now()
    # datetime.weekday(): 周一=0；weekday 参数 1=周一 → 转换
    target_wd = weekday - 1
    days_ahead = (target_wd - now.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7   # 今天这个点已过或就是要下周 → 统一取未来 7 天内最近
    t = (now + timedelta(days=days_ahead)).replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now:
        t += timedelta(days=7)
    return t
