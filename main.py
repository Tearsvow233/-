# -*- coding: utf-8 -*-
"""
BabyCat M5-alpha —— 动作扩展版
M1：透明置顶无边框窗口 + 待机眨眼 + 右键菜单
M2：鼠标拖拽拎着走 + 点击反应（惊讶→开心 + 说话气泡）
M3：自动散步（30fps 平滑移动、屏幕边缘掉头）+ 主动聊天
M4：喝水提醒 + 久坐提醒 + 灵宠中心（改名字/大小/散步/提醒间隔）
M4.1：改名弹窗只在真改名时出现；透明区域点击穿透（setMask）
M4.2：系统托盘（唤回/模式/退出）+ 单实例防双开 + 崩溃日志
M4.3：打包 exe + 开机自启
M5-alpha：从视频提取新动作序列（sleep/stretch/wake/groom），通用序列播放器 + 临时测试按钮
设计原则（用户硬性要求）：
  1. 低资源占用：动画定时器按需启停，静默时零定时器
  2. 占用可设置：正常模式 / 省电静默模式 / 自动散步开关 / 提醒间隔可调
  3. 绝不抢焦点：WindowDoesNotAcceptFocus
说明：提醒是分钟级定时器（成本≈0），静默模式下依然生效——静默只停动画
"""

import os
import sys
import json
import time
import shutil
import action_scheduler
import pet_walk
# T8/T9/T10 的 Qt 集成层 Mixin（T5 行数预算：main.py 只做装配；
# 纯逻辑层在 agent_link / drag_physics / proactive_vision）
from pet_drag import DragMixin
from pet_vision import VisionMixin, build_vision_form, collect_vision_values
from pet_agent_link import AgentLinkMixin
import random
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtGui import QAction, QPixmap, QTransform, QIcon, QPainter, QImageReader, QBitmap, QImage
from PySide6.QtWidgets import (
    QApplication, QLabel, QMenu, QDialog, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLineEdit, QSpinBox, QCheckBox, QPushButton,
    QSystemTrayIcon, QMessageBox, QWidget, QListWidget, QComboBox,
    QScrollArea, QFrame, QSlider,
)
from ai_chat import PetAI
from reminder_parser import parse_reminder, describe as describe_reminder
from datetime import datetime, timedelta
import resources_rc  # noqa: F401  注册 Qt 资源（:/check.png）
import word_push as wp   # 每日英语单词推送（词库/选词/进度/词卡）

# 资源路径：区分"开发环境"和"打包成 exe 后"两种情况
# - 打包后(exe)：素材被打进 exe 内部临时目录 sys._MEIPASS，只读
# - 配置/日志：必须放在 exe 旁边（可写位置），不能放临时目录
def _data_dir():
    if getattr(sys, "frozen", False):          # 被 PyInstaller 打包
        return Path(sys._MEIPASS)
    return Path(__file__).parent

def _app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent     # exe 所在目录
    return Path(__file__).parent

BASE_DIR = _data_dir()
APP_DIR = _app_dir()
SPRITES_DIR = BASE_DIR / "assets" / "sprites"
# T3 图集化：散帧合并成按动作分组的横幅图集（tools/build_atlas.py 生成）。
# 加载优先级：缓存 strip → 图集 → 散帧文件（三层回退）
ATLAS_DIR = BASE_DIR / "assets" / "atlases"
ATLAS_INDEX_FILE = ATLAS_DIR / "atlas_index.json"


def _load_atlas_index():
    """读图集索引；不存在/损坏返回 None（走散帧回退）。索引很小（几十 KB），可反复读"""
    try:
        with open(ATLAS_INDEX_FILE, encoding="utf-8") as f:
            idx = json.load(f)
        if idx.get("version") == 1 and isinstance(idx.get("frames"), dict) and idx["frames"]:
            return idx
    except Exception:
        pass
    return None


# T3 预缩放缓存：按物理像素高度存已缩放的帧图，二次启动免全量解码+缩放。
# 放 APP_DIR（exe 旁可写位置），不能进 _MEIPASS（打包后只读）
SPRITES_CACHE_DIR = APP_DIR / "cache" / "sprites"
SETTINGS_FILE = APP_DIR / "settings.json"      # 配置放 exe 旁边，方便手动改
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "babycat.log"
WORDS_PROGRESS_FILE = APP_DIR / "words_progress.json"   # 每日单词进度（exe 旁，跨日重置）

# ---------- 调试开关：动作测试按钮 ----------
# 功能完善后设为 False 即可移除；True 时会在屏幕左上角显示一个"测动作"按钮
TEST_ACTION_BUTTON = False  # 功能已稳定，测试按钮移除（TestButton 类保留，可随时改回 True）


# ---------- 开机自启（注册表 Run 项，仅 Windows） ----------
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "BabyCat"

def is_autostart():
    try:
        import winreg
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY)
        val, _ = winreg.QueryValueEx(k, RUN_NAME)
        return bool(val)
    except Exception:
        return False

def set_autostart(enable):
    """开启/关闭开机自启。exe 路径取自 sys.executable（打包后即 exe 自身）"""
    try:
        import winreg
        target = f'"{sys.executable}"' if getattr(sys, "frozen", False) \
            else f'"{sys.executable}" "{Path(__file__).resolve()}"'
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                           winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, target)
        else:
            winreg.DeleteValue(k, RUN_NAME)
        log(f"开机自启 -> {enable}")
        return True
    except Exception as e:
        log(f"开机自启设置失败: {e}")
        return False


# ---------- 日志 ----------
def log(msg):
    """追加一行日志（启动、异常、关键事件），失败静默——日志不能拖垮主程序"""
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def install_crash_hook():
    """全局异常钩子：未捕获异常写日志而不是无声消失"""
    def _hook(etype, value, tb):
        log("未捕获异常:\n" + "".join(traceback.format_exception(etype, value, tb)))
        sys.__excepthook__(etype, value, tb)
    sys.excepthook = _hook


wp.LOG_HOOK = log   # word_push 的发音降级/夹屏失败等消息进统一日志


# ---------- 聊天文案 ----------
# 按类别分组；性格（personality）决定各类别的出现权重
CHATTER_GROUPS = {
    "卖萌": ["喵~", "喵呜~", "呜喵~", "喵喵喵~", "呼噜呼噜…", "咕噜咕噜~"],
    "求摸": ["摸摸头！", "要摸摸~", "摸摸我嘛", "挠挠下巴嘛", "撸我一下嘛", "头给你摸，快摸摸"],
    "讨食": ["想吃小鱼干", "有冻干吗？", "罐头罐头！", "肚肚饿啦", "饭饭~饭饭~"],
    "邀玩": ["陪我玩一会儿嘛", "玩逗猫棒吗？", "一起玩嘛", "尾巴给你玩", "来抓我呀~", "爪子借你捏捏"],
    "存在感": ["{name}在呢", "一直陪着你哦", "别走太远嘛", "我就在这儿呀", "看我看我~"],
    "关心": ["今天累了吧？休息一下", "该歇歇啦~", "喝口水吧", "别一直盯着屏幕啦", "站起来走走嘛"],
    "学习": ["今天学 Java 了吗？", "Bug 改完了吗？", "陪你看代码呀", "报错了？我帮你看看（假装会）"],
    "傲娇": ["才、才不是想你呢", "哼，本喵才不稀罕", "勉强陪你一下下", "哼！不理你三秒钟"],
    "困倦": ["好困呀…", "想睡觉觉", "眼皮打架啦", "有点想睡了…"],
    "吐槽": ["你笑什么呀？", "在看什么呀？", "屏幕有我好看吗？", "又在偷偷看手机！"],
    "心情": ["今天心情不错~", "有点无聊呢", "开心开心！", "喵生圆满~"],
}

# 性格预设：label 供下拉显示；weights 决定文案倾向；persona 决定 AI 人设（{name} 占位）
PERSONALITIES = {
    "粘人": {
        "label": "粘人 · 爱撒娇求关注",
        "weights": {"卖萌": 3, "求摸": 4, "存在感": 3, "邀玩": 2, "讨食": 2, "关心": 2, "心情": 1, "傲娇": 1},
        "persona": "你是一只叫{name}的布偶猫桌面宠物，特别粘人、爱撒娇，喜欢求摸摸求抱抱，一刻都不想离开主人。用中文简短回复，不超过30字，多带可爱的语气词。",
    },
    "傲娇": {
        "label": "傲娇 · 口是心非",
        "weights": {"傲娇": 4, "吐槽": 2, "卖萌": 2, "困倦": 1, "关心": 1},
        "persona": "你是一只叫{name}的布偶猫桌面宠物，性格傲娇、口是心非，嘴上嫌弃其实很在乎主人。用中文简短回复，不超过30字，带点傲娇语气。",
    },
    "高冷": {
        "label": "高冷 · 爱答不理",
        "weights": {"吐槽": 4, "傲娇": 3, "困倦": 2, "关心": 1, "卖萌": 1},
        "persona": "你是一只叫{name}的布偶猫桌面宠物，高冷慵懒、爱答不理，偶尔才赏脸理一下主人。用中文极简回复，不超过20字，冷淡但偶尔流露关心。",
    },
    "活泼": {
        "label": "活泼 · 元气满满",
        "weights": {"邀玩": 4, "心情": 3, "卖萌": 2, "存在感": 1, "关心": 1},
        "persona": "你是一只叫{name}的布偶猫桌面宠物，活泼好动、元气满满，总想拉主人一起玩。用中文简短回复，不超过30字，语气轻快有活力。",
    },
    "温柔": {
        "label": "温柔 · 贴心陪伴",
        "weights": {"关心": 4, "存在感": 2, "卖萌": 2, "困倦": 1, "心情": 1},
        "persona": "你是一只叫{name}的布偶猫桌面宠物，温柔贴心、安静陪伴，会关心主人的状态。用中文简短回复，不超过30字，语气温柔。",
    },
}
PERSONALITY_ORDER = ["粘人", "傲娇", "高冷", "活泼", "温柔"]


def build_persona(personality, name):
    """根据性格生成 AI 人设；未识别性格则回退到通用布偶猫人设"""
    p = PERSONALITIES.get(personality)
    if not p:
        return (f"你是一只叫{name}的布偶猫桌面宠物，可爱、有点傲娇、爱撒娇。"
                "用中文简短回复，不超过30字，可以带点语气词。")
    return p["persona"].format(name=name)


# 时间问候：只在对应时段出现（避免"晚上好"在下午乱冒）。区间含头不含尾。
TIME_GREETINGS = [
    (5, 11,  ["早安喵~", "早上好呀，新的一天开始啦~", "起床啦，太阳晒屁股啦~"]),
    (11, 18, ["下午好呀", "下午茶时间到~", "下午也要元气满满喵~"]),
    (18, 23, ["晚上好喵~", "晚饭吃了吗？", "晚上一起玩耍吧~"]),
    (23, 24, ["夜深啦，早点睡", "这么晚还不睡？熬夜会掉毛哦", "晚安喵~"]),
    (0, 5,   ["夜深啦，早点睡", "还不睡吗？明天会困哦", "晚安喵~"]),
]
WEEKEND_GREETINGS = ["周末快乐喵！", "周末啦，好好休息~", "周末想出去玩~"]

WATER_TEXTS = [
    "该喝水啦！咕咚咕咚~", "喝水时间到！保持水分~", "{name}盯着你，快喝水！",
    "杯子举起来，喝水喝水~", "水水水，身体需要水~", "你多久没喝水啦？",
    "喝口水休息一下吧~", "嘴唇干了吧？去喝水~", "咕嘟咕嘟，快去喝~",
    "健康小贴士：现在该喝水啦",
]

SIT_TEXTS = [
    "坐太久啦，起来活动一下！", "陪你去窗边看看远处~", "伸个懒腰吧，腰会感谢你的！",
    "起来走两步嘛~", "脖子酸了吧？转转脑袋~", "久坐伤身，站起来动动~",
    "小江陪你做个伸展~", "去倒杯水顺便活动下~", "再坐下去要变石头啦！",
    "起来跳一跳，血液循环~",
]

# ---------- 新动作配置 ----------
# fps：序列播放帧率；weight：随机触发权重（暂未启用，保留字段）
# 注意：recoil/spin/pace 素材已按视频 24fps 原速逐帧提取 → fps=24 即原速播放
# loops: 有限循环次数（>1 表示重复播几轮）；loop:True 表示无限循环；
# auto:  是否纳入空闲自动触发（sleep/wake/settle 由入睡状态机专用，不随机触发）
ACTIONS = {
    "sleep":       {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": False},  # 入睡状态机专用
    "stretch":     {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": True},
    "walk_circle": {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": True},
    "wake":        {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": False},  # 唤醒专用
    "groom":       {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": True},
    "settle":      {"fps": 7, "loop": False, "loops": 1, "weight": 1, "auto": False},  # 入睡收尾专用
    "recoil":      {"fps": 24, "loop": False, "loops": 1, "weight": 1, "auto": False},  # 点击反馈：后仰站起（2.5s/60帧）
    "spin":        {"fps": 24, "loop": False, "loops": 1, "weight": 1, "auto": True},   # 抬手+歪头+转圈（5s/120帧）
    "pace":        {"fps": 24, "loop": False, "loops": 1, "weight": 1, "auto": True},   # 左右移动踱步（8s/192帧）
}
ACTION_LABELS = {  # 测试按钮 / 提示用
    "sleep": "睡觉", "stretch": "伸懒腰", "walk_circle": "转圈走动",
    "wake": "睡醒张望", "groom": "舔爪洗脸", "settle": "蜷回去睡",
    "recoil": "后仰站起", "spin": "抬手转圈", "pace": "左右踱步",
}


# ---------- 显示尺寸自适应（上下限 + 按屏幕比例 + 用户相对系数） ----------
MIN_PET_H = 80            # 显示高度下限 px：再小五官就看不清了
MAX_PET_H = 240           # 显示高度上限 px：4K 屏也不喧宾夺主
PET_H_RATIO = 0.11        # 占当前屏可用高度的比例（1080p→119 / 1440p→158 / 4K→237）
MIN_H_FACTOR = 0.75       # 用户体型系数下限（相对当前屏基准）
MAX_H_FACTOR = 1.25       # 用户体型系数上限
H_RELOAD_DELTA = 4        # 跨屏重算后高度差不足该值就不重载素材（解码约 7s，必须节流）
FALLBACK_SCREEN_H = 1080  # 取不到屏幕时的兜底可用高度


# ---------- 设置读写 ----------
DEFAULT_SETTINGS = {
    "pet_name": "小江",    # 灵宠名字（随时可改）
    "height": 100,         # 【旧键】仅供老配置迁移读取；当前高度由 height_factor × 屏幕算出
    "height_factor": 1.0,  # 体型系数：相对当前屏基准高度（0.75~1.25）
    "mode": "normal",      # normal=正常眨眼 / silent=省电静默
    "auto_walk": True,     # 是否自动散步
    "drag_physics": False,  # T10 拖拽弹射：甩抛+重力+屏幕反弹（默认关，避免拖动误触；灵宠中心可开）
    # 自定义提醒列表（L1 升级：纯本地定时器，零 API 成本）
    # 喝水/久坐等提醒统一走 reminders（旧 water_min/sit_min 启动时自动迁移）
    # 每项：{"name": "...", "interval_min": N, "enabled": True}
    "reminders": [],
    "pos_x": None,         # 记住上次位置
    "pos_y": None,
    # ---- 性格与行为节奏（可在灵宠中心自定义）----
    "personality": "粘人",    # 性格：粘人/傲娇/高冷/活泼/温柔（影响文案倾向 + AI 人设）
    "sleep_after_min": 5,     # 入睡等待（分钟，0=关闭）：无互动且系统空闲达到该时长后入睡
    "action_min_sec": 10,     # 随机空闲动作最小间隔（秒）
    "action_max_sec": 30,     # 随机空闲动作最大间隔（秒）
    "walk_min_sec": 12,       # 自动散步最小间隔（秒）
    "walk_max_sec": 30,       # 自动散步最大间隔（秒）
    "chat_min_sec": 40,       # 主动说话最小间隔（秒）
    "chat_max_sec": 90,       # 主动说话最大间隔（秒）
    "blink_min_sec": 3,       # 眨眼最小间隔（秒）
    "blink_max_sec": 7,       # 眨眼最大间隔（秒）
    # ---- AI 对话（可选；不填 key 则自动用内置文案兜底）----
    "ai_enabled": False,
    "ai_api_key": "",
    "ai_base_url": "https://api.openai.com/v1",
    "ai_model": "gpt-4o-mini",
    "ai_persona": "",       # 留空 = 按「性格」自动生成人设；也可手动填自定义人设
    # ---- T8 proactive 主动行为（隐私优先：默认关，且只看白名单里的前台应用）----
    "proactive_vision": False,          # 空闲时截图看一眼并主动搭话（需启用 AI）
    "vision_idle_min": 10,              # 画面+人都静止多少分钟才算"闲置"（触发阈值）
    "vision_check_sec": 60,             # 每 N 秒截一张 9×8 缩略图做哈希比对
    "vision_cooldown_min": 30,         # 主动搭话一次后冷却多少分钟
    "vision_process_whitelist": [       # 只允许在这些前台应用上截图送模型（隐私红线）
        "chrome", "msedge", "firefox", "code", "idea64", "pycharm64",
        "devenv", "notepad", "obsidian", "typora", "explorer",
    ],
    "ai_vision_model": "",              # 视觉模型名；留空回落 ai_model（需支持图片）
    # ---- 每日英语单词推送（本地词库，每天一次）----
    "word_enabled": True,   # 开关（灵宠中心可关）
    "word_count": 10,       # 每天推送词量（5~20，默认 10）
    # ---- Agent Link 事件总线（T9：让外部 Agent 驱动宠物动作）----
    "agent_link_enabled": False,   # 默认关；开了会在 <config_dir>/agent-events 监听 .jsonl
    "agent_link_poll_ms": 500,     # 轮询间隔 ms（500ms 足够灵敏，几乎无磁盘负担）
    "agent_link_stale_sec": 60,    # 某 agent 多久没新事件 → 回退 idle
    # 6 态 → 动作 的映射（v1 写死在 settings 不做 UI；想改直接改 settings.json）
    "agent_link_to_action": {
        "thinking":  "spin",
        "working":   "pace",
        "attention": "recoil",
        "error":     "spin",
    },
}

def _primary_screen():
    """主屏；还没有 QApplication 时返回 None（调用方需兜底）"""
    try:
        return QApplication.primaryScreen()
    except Exception:
        return None


def display_height_for(screen, factor=1.0):
    """给定屏幕与用户体型系数 → 显示高度（px）。

    h = clamp(round(屏可用高度 × PET_H_RATIO × factor), MIN_PET_H, MAX_PET_H)
    系数与结果都要钳制：再极端的偏好也不越界。
    """
    try:
        f = float(factor)
    except Exception:
        f = 1.0
    f = max(MIN_H_FACTOR, min(MAX_H_FACTOR, f))
    avail_h = 0
    if screen is not None:
        try:
            avail_h = screen.availableGeometry().height()
        except Exception:
            avail_h = 0
    if avail_h <= 0:
        avail_h = FALLBACK_SCREEN_H
    return max(MIN_PET_H, min(MAX_PET_H,
                              int(round(avail_h * PET_H_RATIO * f))))


def migrate_height_factor(old_height):
    """旧配置里的绝对 height(px) → 相对系数 height_factor（钳制 0.75~1.25）。

    基准取「当前屏可用高度 × PET_H_RATIO」；取不到屏或旧值非法时退化为 1.0。
    """
    try:
        old_h = float(old_height or 0)
    except Exception:
        return 1.0
    avail_h = 0
    scr = _primary_screen()
    if scr is not None:
        try:
            avail_h = scr.availableGeometry().height()
        except Exception:
            avail_h = 0
    if old_h <= 0 or avail_h <= 0:
        return 1.0
    return max(MIN_H_FACTOR, min(MAX_H_FACTOR,
                                 round(old_h / (avail_h * PET_H_RATIO), 2)))


def load_settings():
    data = dict(DEFAULT_SETTINGS)
    if SETTINGS_FILE.exists():
        try:
            raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except Exception:
            raw = {}
        data.update(raw)
        # 旧配置迁移：只有绝对 height → 换算成相对系数（不动其他字段）
        if "height_factor" not in raw:
            f = migrate_height_factor(raw.get("height"))
            data["height_factor"] = f
            log(f"[migrate] 旧 height={raw.get('height')} → height_factor={f}")
    return data

def save_settings(settings):
    SETTINGS_FILE.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def migrate_legacy_reminders(settings):
    """旧版独立 water_min/sit_min → 迁移为 reminders 自定义提醒（幂等）。

    若旧 settings 含 water_min/sit_min（>0）且列表中还没有同名提醒，就补一条
    interval 循环提醒，然后移除旧键；发生任何改动才写回一次 settings.json。
    """
    reminders = settings.setdefault("reminders", [])
    changed = False
    try:
        w = int(settings.get("water_min") or 0)
    except Exception:
        w = 0
    if w > 0 and not any("喝水" in (r.get("name") or "") for r in reminders):
        reminders.append({"name": "喝水", "mode": "interval",
                          "interval_min": w, "once": False, "enabled": True})
        log(f"[migrate] 旧 water_min={w} → 迁移为「喝水」提醒")
        changed = True
    try:
        s = int(settings.get("sit_min") or 0)
    except Exception:
        s = 0
    if s > 0 and not any(("起来活动" in (r.get("name") or ""))
                         or ("久坐" in (r.get("name") or "")) for r in reminders):
        reminders.append({"name": "起来活动一下", "mode": "interval",
                          "interval_min": s, "once": False, "enabled": True})
        log(f"[migrate] 旧 sit_min={s} → 迁移为「起来活动一下」提醒")
        changed = True
    if "water_min" in settings:
        settings.pop("water_min")
        changed = True
    if "sit_min" in settings:
        settings.pop("sit_min")
        changed = True
    if changed:
        save_settings(settings)
    return changed


# ---------- 说话气泡（独立的临时小窗） ----------
class Bubble(QLabel):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            "QLabel { background: rgba(255,255,255,235); color: #3C3489;"
            "border: 1.5px solid #534AB7; border-radius: 10px;"
            "padding: 5px 10px; font-size: 13px; }"
        )
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)

    def say(self, text, anchor, ms=2600):
        """anchor = (x, y, width)：气泡出现在小江头顶上方"""
        self.setText(text)
        self.adjustSize()
        self._anchor = anchor
        self.reposition()
        self.show()
        self.raise_()
        self.hide_timer.start(ms)

    def reposition(self):
        """按当前 _anchor 重新定位（用于窗口被拖动时同步跟随）"""
        if not hasattr(self, "_anchor"):
            return
        anchor = self._anchor
        bx = anchor[0] + anchor[2] // 2 - self.width() // 2
        by = anchor[1] - self.height() - 6
        self.move(max(bx, 0), max(by, 0))

    def follow(self, anchor):
        """窗口移动时同步更新气泡位置；不重置 hide_timer"""
        self._anchor = anchor
        if self.isVisible():
            self.reposition()


# ---------- AI 聊天后台线程（避免请求时卡 UI） ----------
class ChatWorker(QThread):
    result_ready = Signal(object)   # str 或 None（None/出错 -> 调用方回退）

    def __init__(self, ai, user_text, history):
        super().__init__()
        self.ai = ai
        self.user_text = user_text
        self.history = history

    def run(self):
        try:
            ans = self.ai.reply(self.user_text, self.history)
        except Exception:
            ans = None
        self.result_ready.emit(ans)


class ReminderParseWorker(QThread):
    """L3：后台线程调 LLM 把一句话解析成提醒 dict（不卡 UI）"""
    result_ready = Signal(object)   # dict | None

    def __init__(self, ai, text):
        super().__init__()
        self.ai = ai
        self.text = text

    def run(self):
        try:
            r = self.ai.parse_reminder_spec(self.text)
        except Exception:
            r = None
        self.result_ready.emit(r)


# ---------- 暗色玻璃弹窗主题（B 方案） ----------
# 作用域限定在 QDialog 及其子控件：设置面板 / AI 聊天 / 提醒输入 / 消息框
DIALOG_QSS = """
QDialog {
    background-color: #26262F;
}
QDialog QLabel {
    color: #E8E8F0;
    background: transparent;
}
QDialog QLineEdit,
QDialog QSpinBox,
QDialog QListWidget,
QDialog QTextEdit {
    background-color: #1C1C24;
    color: #F0F0F6;
    border: 1px solid #3A3A46;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: #3DD6B0;
    selection-color: #0E241D;
}
QDialog QLineEdit:focus,
QDialog QSpinBox:focus,
QDialog QTextEdit:focus,
QDialog QListWidget:focus {
    border: 1px solid #3DD6B0;
}
QDialog QSpinBox::up-button,
QDialog QSpinBox::down-button {
    background: #2E2E38;
    border: none;
    width: 18px;
    border-radius: 4px;
    margin: 2px;
}
QDialog QSpinBox::up-button:hover,
QDialog QSpinBox::down-button:hover {
    background: #3A3A46;
}
QDialog QCheckBox {
    color: #E8E8F0;
    spacing: 8px;
    font-size: 13px;
    background: transparent;
}
QDialog QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #4A4A58;
    background: #1C1C24;
}
QDialog QCheckBox::indicator:checked {
    background: #3DD6B0;
    border: 1px solid #3DD6B0;
    image: url(:/check.png);
}
QDialog QPushButton {
    background-color: #2E2E38;
    color: #ECECF2;
    border: 1px solid #4A4A58;
    border-radius: 8px;
    padding: 7px 16px;
    font-size: 13px;
    min-width: 64px;
}
QDialog QPushButton:hover {
    background-color: #3A3A46;
    border-color: #3DD6B0;
}
QDialog QPushButton:pressed {
    background-color: #484858;
}
QDialog QPushButton:default {
    background-color: #3DD6B0;
    color: #0E241D;
    border: 1px solid #3DD6B0;
    font-weight: bold;
}
QDialog QPushButton:default:hover {
    background-color: #4DE0BC;
    border-color: #4DE0BC;
}
QDialog QListWidget {
    padding: 4px;
    outline: 0;
}
QDialog QListWidget::item {
    padding: 5px 8px;
    border-radius: 5px;
}
QDialog QListWidget::item:selected {
    background: #3DD6B0;
    color: #0E241D;
}
QMessageBox {
    background-color: #26262F;
}
QMessageBox QLabel {
    color: #E8E8F0;
}
"""


# ---------- 灵宠中心（设置面板） ----------
class PetCenter(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle(f"灵宠中心 · {settings['pet_name']}")
        self.setMinimumWidth(340)

        # 滚动容器：设置项多时也能在小屏幕内滚动查看，不会撑爆窗口
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        form = QFormLayout()

        self.name_edit = QLineEdit(settings["pet_name"])
        self.name_edit.setMaxLength(12)
        form.addRow("名字", self.name_edit)

        # 体型：相对系数滑块（0.75×~1.25×），实际高度按当前屏自适应
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(75, 125)          # 整数档位 = 系数 × 100
        self.size_slider.setSingleStep(5)           # 步进 0.05
        self.size_slider.setPageStep(5)
        self.size_slider.setTickInterval(5)
        self.size_slider.setValue(int(round(float(
            settings.get("height_factor", 1.0)) * 100)))
        self.size_label = QLabel()
        self.size_label.setStyleSheet("color: #E8E8F0; font-size: 12px;")
        size_box = QWidget()
        size_lay = QVBoxLayout(size_box)
        size_lay.setContentsMargins(0, 0, 0, 0)
        size_lay.setSpacing(2)
        size_lay.addWidget(self.size_slider)
        size_lay.addWidget(self.size_label)
        size_hint = QLabel("范围 80 – 240 px · 随屏幕自动适配")
        size_hint.setStyleSheet("color: #9A9AA8; font-size: 11px;")
        size_lay.addWidget(size_hint)
        self.size_slider.valueChanged.connect(self._refresh_size_label)
        self._refresh_size_label()
        form.addRow("体型", size_box)

        self.walk_check = QCheckBox("自动散步（待机时自己溜达）")
        self.walk_check.setChecked(settings["auto_walk"])
        form.addRow("", self.walk_check)

        self.physics_check = QCheckBox("拖拽弹射（甩出去会撞屏弹跳；关闭则松手即停）")
        self.physics_check.setChecked(settings.get("drag_physics", False))
        form.addRow("", self.physics_check)

        self.autostart_check = QCheckBox("开机自动启动小江")
        self.autostart_check.setChecked(is_autostart())
        form.addRow("", self.autostart_check)

        # ---- 性格与行为节奏（用户可自定义）----
        beh_sep = QLabel("性格与行为节奏")
        beh_sep.setStyleSheet("color: #3DD6B0; font-size: 11px; font-weight: bold;")
        form.addRow(beh_sep)

        self.personality_combo = QComboBox()
        for key in PERSONALITY_ORDER:
            self.personality_combo.addItem(PERSONALITIES[key]["label"], key)
        cur_personality = settings.get("personality", "粘人")
        pidx = PERSONALITY_ORDER.index(cur_personality) if cur_personality in PERSONALITY_ORDER else 0
        self.personality_combo.setCurrentIndex(pidx)
        form.addRow("性格", self.personality_combo)

        self.action_min_spin = QSpinBox(); self.action_min_spin.setRange(3, 300)
        self.action_min_spin.setValue(settings.get("action_min_sec", 10)); self.action_min_spin.setSuffix(" 秒")
        self.action_max_spin = QSpinBox(); self.action_max_spin.setRange(3, 600)
        self.action_max_spin.setValue(settings.get("action_max_sec", 30)); self.action_max_spin.setSuffix(" 秒")
        form.addRow("动作间隔", self._minmax_row(self.action_min_spin, self.action_max_spin))

        self.walk_min_spin = QSpinBox(); self.walk_min_spin.setRange(5, 600)
        self.walk_min_spin.setValue(settings.get("walk_min_sec", 12)); self.walk_min_spin.setSuffix(" 秒")
        self.walk_max_spin = QSpinBox(); self.walk_max_spin.setRange(5, 1200)
        self.walk_max_spin.setValue(settings.get("walk_max_sec", 30)); self.walk_max_spin.setSuffix(" 秒")
        form.addRow("散步间隔", self._minmax_row(self.walk_min_spin, self.walk_max_spin))

        self.chat_min_spin = QSpinBox(); self.chat_min_spin.setRange(5, 3600)
        self.chat_min_spin.setValue(settings.get("chat_min_sec", 40)); self.chat_min_spin.setSuffix(" 秒")
        self.chat_max_spin = QSpinBox(); self.chat_max_spin.setRange(5, 7200)
        self.chat_max_spin.setValue(settings.get("chat_max_sec", 90)); self.chat_max_spin.setSuffix(" 秒")
        form.addRow("主动说话间隔", self._minmax_row(self.chat_min_spin, self.chat_max_spin))

        self.blink_min_spin = QSpinBox(); self.blink_min_spin.setRange(1, 60)
        self.blink_min_spin.setValue(settings.get("blink_min_sec", 3)); self.blink_min_spin.setSuffix(" 秒")
        self.blink_max_spin = QSpinBox(); self.blink_max_spin.setRange(1, 120)
        self.blink_max_spin.setValue(settings.get("blink_max_sec", 7)); self.blink_max_spin.setSuffix(" 秒")
        form.addRow("眨眼间隔", self._minmax_row(self.blink_min_spin, self.blink_max_spin))

        self.sleep_spin = QSpinBox()
        self.sleep_spin.setRange(0, 120)
        self.sleep_spin.setValue(settings.get("sleep_after_min", 5))
        self.sleep_spin.setSuffix(" 分钟")
        self.sleep_spin.setSpecialValueText("关闭")
        form.addRow("入睡等待", self.sleep_spin)

        # ---- 自定义提醒（L1：纯本地定时器，零 API 成本）----
        rem_sep = QLabel("自定义提醒（本地定时器，零 API 成本）")
        rem_sep.setStyleSheet("color: #3DD6B0; font-size: 11px; font-weight: bold;")
        form.addRow(rem_sep)

        # 工作副本：只在点「保存」时提交（点「取消」不污染正式设置）
        self.reminders_work = [dict(r) for r in settings.get("reminders", [])]
        self._llm_worker = None
        self._pending_llm_text = ""
        self.rem_list = QListWidget()
        self.rem_list.setMaximumHeight(80)
        self._refresh_rem_list()
        form.addRow(self.rem_list)

        rem_btns = QHBoxLayout()
        add_btn = QPushButton("＋ 添加提醒")
        del_btn = QPushButton("－ 删除选中")
        add_btn.clicked.connect(self._add_reminder)
        del_btn.clicked.connect(self._del_reminder)
        rem_btns.addWidget(add_btn)
        rem_btns.addWidget(del_btn)
        rem_btns.addStretch()
        form.addRow("", rem_btns)

        # 常用模板：一键生成喝水/久坐的循环 interval 提醒（统一走 reminders 管理）
        tmpl_btns = QHBoxLayout()
        water_tmpl_btn = QPushButton("＋ 喝水提醒")
        sit_tmpl_btn = QPushButton("＋ 久坐提醒")
        water_tmpl_btn.clicked.connect(
            lambda: self._add_interval_template("喝水", 45, "喝水"))
        sit_tmpl_btn.clicked.connect(
            lambda: self._add_interval_template("起来活动一下", 60, "起身活动"))
        tmpl_btns.addWidget(water_tmpl_btn)
        tmpl_btns.addWidget(sit_tmpl_btn)
        tmpl_btns.addStretch()
        form.addRow("模板", tmpl_btns)

        # ---- 每日单词（本地四级词库，每天一次）----
        word_sep = QLabel("每日单词（每天推送一次四级核心词）")
        word_sep.setStyleSheet("color: #3DD6B0; font-size: 11px; font-weight: bold;")
        form.addRow(word_sep)

        self.word_check = QCheckBox("启用每日单词推送")
        self.word_check.setChecked(bool(settings.get("word_enabled", True)))
        form.addRow("", self.word_check)

        self.word_spin = QSpinBox()
        self.word_spin.setRange(5, 20)
        self.word_spin.setValue(int(settings.get("word_count", 10)))
        self.word_spin.setSuffix(" 词/天")
        form.addRow("每日词量", self.word_spin)

        word_note = QLabel("当天词量分小批（每批 2 个），09:00~20:30 到点在猫头顶弹"
                           "小气泡卡，45 秒自动关；点单词可听发音。"
                           "睡着时被推会先醒过来教词，卡片关掉后继续睡。")
        word_note.setStyleSheet("color: #9A9AA8; font-size: 11px;")
        word_note.setWordWrap(True)
        form.addRow("", word_note)

        # ---- AI 聊天（可选）----
        ai_sep = QLabel("AI 聊天（可选，不填 key 则用内置卖萌文案）")
        ai_sep.setStyleSheet("color: #3DD6B0; font-size: 11px; font-weight: bold;")
        form.addRow(ai_sep)

        self.ai_check = QCheckBox("启用 AI 对话（双击猫咪 / 托盘可聊）")
        self.ai_check.setChecked(bool(settings.get("ai_enabled", False)))
        form.addRow("", self.ai_check)

        self.ai_key_edit = QLineEdit(settings.get("ai_api_key", ""))
        self.ai_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key_edit.setPlaceholderText("OpenAI / 兼容服务的 API Key")
        form.addRow("API Key", self.ai_key_edit)

        self.ai_base_edit = QLineEdit(settings.get("ai_base_url", "https://api.openai.com/v1"))
        self.ai_base_edit.setPlaceholderText("接口地址（兼容 OpenAI /v1/chat/completions）")
        form.addRow("接口地址", self.ai_base_edit)

        self.ai_model_edit = QLineEdit(settings.get("ai_model", "gpt-4o-mini"))
        self.ai_model_edit.setPlaceholderText("模型名")
        form.addRow("模型", self.ai_model_edit)

        # T8 主动观察：控件在 pet_vision.build_vision_form（行数预算拆分）
        self._vision_widgets = build_vision_form(form, settings)

        layout.addLayout(form)

        note = QLabel("自定义提醒统一管理喝水/久坐等所有周期性提醒（用上方模板一键添加）；提醒在省电静默模式下依然生效（只停动画）。入睡等待设为 0 表示关闭。")
        note.setStyleSheet("color: #9A9AA8; font-size: 11px;")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        ok = QPushButton("保存")
        ok.setDefault(True)
        cancel = QPushButton("取消")
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        buttons.addStretch()
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)

        # 把内容装进滚动区；禁止横向滚动，宽度改由窗口本身吃下内容
        scroll.setWidget(container)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # 尺寸适配：宽度以内容最小宽度为基准留足余量，杜绝横向滚动/左右拖动；
        # 高度按屏幕 85% 封顶，超出部分纵向滚动
        try:
            screen = QApplication.primaryScreen().availableGeometry()
            max_h = int(screen.height() * 0.85)
            scroll.setMaximumHeight(max_h)

            container.layout().activate()
            need_w = container.minimumSizeHint().width()
            vbar_w = scroll.verticalScrollBar().sizeHint().width() or 12
            fit_w = need_w + vbar_w + 2          # 内容不再横向溢出的最小窗口宽
            comf_w = min(max(fit_w + 100, 560), 640)   # 舒适打开宽度
            want_h = container.sizeHint().height() + 10

            self.setMinimumWidth(min(fit_w, max(340, screen.width() - 40)))
            self.resize(min(comf_w, screen.width() - 20),
                        min(max(want_h, 420), max_h))
        except Exception:
            pass

    def showEvent(self, e):
        """显示时把窗口夹回屏幕内（小江停在屏幕右缘时，居中弹窗不会探出屏幕）"""
        super().showEvent(e)
        try:
            parent = self.parentWidget()
            scr = parent.screen() if (parent and parent.screen()) else QApplication.primaryScreen()
            ag = scr.availableGeometry()
            g = self.geometry()
            if g.right() > ag.right():
                g.moveRight(ag.right())
            if g.left() < ag.left():
                g.moveLeft(ag.left())
            if g.bottom() > ag.bottom():
                g.moveBottom(ag.bottom())
            if g.top() < ag.top():
                g.moveTop(ag.top())
            self.setGeometry(g)
        except Exception:
            pass

    def _center_screen(self):
        """本屏：优先跟随小江所在屏（parent），取不到时回落主屏"""
        parent = self.parentWidget()
        scr = parent.screen() if parent is not None else None
        if scr is None:
            scr = QApplication.primaryScreen()
        return scr

    def _refresh_size_label(self):
        """实时显示当前体型系数在本屏上对应的显示高度"""
        factor = self.size_slider.value() / 100.0
        h = display_height_for(self._center_screen(), factor)
        self.size_label.setText(f"当前约 {h} px（本屏） · {factor:.2f}×")

    def _minmax_row(self, lo, hi):
        """「最小值 ~ 最大值」组合控件行（间隔类设置的通用布局）"""
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(lo)
        tilde = QLabel("~")
        tilde.setStyleSheet("color: #9A9AA8;")
        h.addWidget(tilde)
        h.addWidget(hi)
        return box

    @staticmethod
    def _minmax_pair(lo, hi):
        """保证 min<=max（用户可能把最小值设得比最大值大）"""
        return min(lo, hi), max(lo, hi)

    def values(self):
        amn, amx = self._minmax_pair(self.action_min_spin.value(), self.action_max_spin.value())
        wmn, wmx = self._minmax_pair(self.walk_min_spin.value(), self.walk_max_spin.value())
        cmn, cmx = self._minmax_pair(self.chat_min_spin.value(), self.chat_max_spin.value())
        bmn, bmx = self._minmax_pair(self.blink_min_spin.value(), self.blink_max_spin.value())
        return {
            "pet_name": self.name_edit.text().strip() or "小江",
            "height_factor": round(self.size_slider.value() / 100.0, 2),
            "auto_walk": self.walk_check.isChecked(), "drag_physics": self.physics_check.isChecked(),
            "autostart": self.autostart_check.isChecked(),   # 不写进 settings
            "reminders": self.reminders_work,  # 自定义提醒列表（工作副本，点保存才提交）
            # 性格与行为节奏
            "personality": self.personality_combo.currentData(),
            "sleep_after_min": self.sleep_spin.value(),
            "action_min_sec": amn, "action_max_sec": amx,
            "walk_min_sec": wmn, "walk_max_sec": wmx,
            "chat_min_sec": cmn, "chat_max_sec": cmx,
            "blink_min_sec": bmn, "blink_max_sec": bmx,
            # AI
            "ai_enabled": self.ai_check.isChecked(),
            "ai_api_key": self.ai_key_edit.text().strip(),
            "ai_base_url": self.ai_base_edit.text().strip() or "https://api.openai.com/v1",
            "ai_model": self.ai_model_edit.text().strip() or "gpt-4o-mini",
            # T8 主动观察（收集逻辑在 pet_vision.collect_vision_values）
            **collect_vision_values(self._vision_widgets),
            # 每日单词
            "word_enabled": self.word_check.isChecked(),
            "word_count": self.word_spin.value(),
        }

    # ---------- 自定义提醒列表（L1/L2 共用）----------
    def _refresh_rem_list(self):
        """刷新灵宠中心里显示的提醒列表（interval/daily/weekly 通用）"""
        self.rem_list.clear()
        for r in self.reminders_work:
            mark = "●" if r.get("enabled", True) else "○"
            desc = describe_reminder(r)
            self.rem_list.addItem(f"{mark} {desc}" if desc else f"{mark} {r.get('name', '')}")

    def _add_reminder(self):
        """添加提醒：输入一句自然语言会自动解析（L2 → L3 LLM → 手动回退）"""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "添加提醒",
            "提醒什么？\n一句话即可（小江会自动听懂）：\n"
            "· 45分钟后提醒我下课\n· 明天早上9点提醒交作业\n· 每周一晚上8点提醒开会")
        if not ok or not text.strip():
            return
        text = text.strip()
        parsed = parse_reminder(text)
        if parsed:
            self.reminders_work.append(parsed)
            self._refresh_rem_list()
            return
        # L2 听不懂 → 交给 L3（LLM，异步；未启用 AI 直接手动回退）
        self._llm_try_parse(text)

    def _llm_try_parse(self, text):
        """L3：后台 LLM 解析一句话（连 bound method，dialog 关闭自动断开，安全）"""
        if not (self.settings.get("ai_enabled") and self.settings.get("ai_api_key")):
            self._manual_fallback(text)
            return
        self.rem_list.addItem("🤔 小江在想…（AI 解析中）")
        self._pending_llm_text = text
        self._llm_worker = ReminderParseWorker(PetAI(self.settings), text)
        self._llm_worker.result_ready.connect(self._on_llm_try)
        self._llm_worker.start()

    def _on_llm_try(self, r):
        """L3 结果回到 UI 线程：成功入库 / 失败手动回退"""
        self._llm_worker = None
        # 移除"AI 解析中"占位项
        for i in range(self.rem_list.count()):
            item = self.rem_list.item(i)
            if item and item.text().startswith("🤔"):
                self.rem_list.takeItem(i)
                break
        text = getattr(self, "_pending_llm_text", "")
        if r:
            self.reminders_work.append(r)
            self._refresh_rem_list()
        else:
            self._manual_fallback(text)

    def _manual_fallback(self, text):
        """最后兜底：手动填循环间隔（L1 语义）"""
        from PySide6.QtWidgets import QInputDialog
        mins, ok2 = QInputDialog.getInt(self, "添加提醒",
            f"这句小江没听懂，手动设置：\n「{text}」每多少分钟提醒一次？", 60, 1, 1440)
        if not ok2:
            return
        self.reminders_work.append({
            "name": text, "interval_min": int(mins), "enabled": True,
        })
        self._refresh_rem_list()

    def _del_reminder(self):
        """删除选中的提醒"""
        row = self.rem_list.currentRow()
        if 0 <= row < len(self.reminders_work):
            self.reminders_work.pop(row)
            self._refresh_rem_list()

    def _add_interval_template(self, name, default_min, label):
        """一键添加「喝水 / 久坐」循环提醒：弹一个分钟数输入框（默认值见参数）"""
        from PySide6.QtWidgets import QInputDialog
        mins, ok = QInputDialog.getInt(
            self, f"{label}提醒", f"每隔多少分钟提醒「{name}」？",
            default_min, 1, 1440)
        if not ok:
            return
        # 已存在同名提醒则不重复添加
        if any(r.get("name") == name for r in self.reminders_work):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "灵宠中心", f"已存在「{name}」提醒，无需重复添加")
            return
        self.reminders_work.append({
            "name": name, "mode": "interval",
            "interval_min": int(mins), "once": False, "enabled": True,
        })
        self._refresh_rem_list()


# ---------- 聊天输入框 ----------
class ChatInputDialog(QDialog):
    """双击猫咪弹的聊天输入框。
    标题栏刻意置空（不带任何宠物名/标题文字，仅图标，仍可拖动/关闭）；
    样式走全局 DIALOG_QSS（QDialog 作用域），Enter 确定、Esc 取消。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("")          # 验收：不出现宠物名等标题文字
        label = QLabel("说点什么：")
        self.edit = QLineEdit()
        ok = QPushButton("确定")
        ok.setDefault(True)              # Enter 触发确定
        cancel = QPushButton("取消")       # Esc 由 QDialog 默认 reject
        ok.clicked.connect(self.accept)
        cancel.clicked.connect(self.reject)
        btns = QHBoxLayout()
        btns.addStretch()
        btns.addWidget(ok)
        btns.addWidget(cancel)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(label)
        lay.addWidget(self.edit)
        lay.addLayout(btns)
        self.setMinimumWidth(280)

    def text(self):
        return self.edit.text().strip()


# ---------- 临时动作测试按钮 ----------
class TestButton(QWidget):
    def __init__(self, pet):
        super().__init__()
        self.pet = pet
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.btn = QPushButton("测动作")
        self.btn.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,200); color: #333;"
            "border: 1px solid #999; border-radius: 6px; padding: 4px 10px; font-size: 12px; }"
            "QPushButton:hover { background: rgba(240,240,255,230); }"
        )
        self.btn.setToolTip("点击循环测试 sleep / stretch / wake / groom")
        self.btn.clicked.connect(self.on_click)
        layout.addWidget(self.btn)
        self.adjustSize()
        # 放在屏幕左上角，不挡小江默认位置
        self.move(20, 200)

    def on_click(self):
        self.pet.test_action()


# ---------- 主窗口：小江本体 ----------
class PetWindow(AgentLinkMixin, DragMixin, VisionMixin, QLabel):
    # T9：AgentLink 在 daemon 线程触发，emit() 跨线程安全；slot 在主线程跑
    agent_state = Signal(str, dict)  # (state, {agent: (state, ts)})

    def __init__(self, settings):
        super().__init__()
        self.settings = settings
        self.bubble = Bubble()

        # 无边框 + 置顶 + 不在任务栏 + 不抢焦点
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        # ----- 状态机 -----
        # idle（待机眨眼） / walk（散步） / react（被点击反应） / drag（被拎着） / action（新动作序列）
        self.state = "idle"

        # 新动作播放器相关
        self.action_frames = {}      # name -> [QPixmap, ...]
        self.action_name = None
        self.action_idx = 0
        self.action_timer = QTimer(self)
        self.action_timer.timeout.connect(self.action_step)

        # 空闲时随机自动触发动作（不用干等手动按钮）
        self.auto_action_timer = QTimer(self); self.auto_action_timer.setSingleShot(True)
        self.auto_action_timer.timeout.connect(self.maybe_auto_action)

        # 眨眼：单次定时器，随机 3~7 秒
        self.blink_timer = QTimer(self); self.blink_timer.setSingleShot(True)
        self.blink_timer.timeout.connect(self.do_blink)
        self.unblink_timer = QTimer(self); self.unblink_timer.setSingleShot(True)
        self.unblink_timer.timeout.connect(self.undo_blink)

        # 反应链：惊讶 500ms → 开心 900ms → 回到待机
        self.react_timer = QTimer(self); self.react_timer.setSingleShot(True)
        self.react_timer.timeout.connect(self.next_react)

        # 散步：33ms 一拍（约 30fps，位置平滑移动），帧切换每 3 拍一换
        self.walk_timer = QTimer(self)
        self.walk_timer.timeout.connect(self.walk_step)

        # 行为调度：随机 10~25 秒后开始下一次散步
        self.behavior_timer = QTimer(self); self.behavior_timer.setSingleShot(True)
        self.behavior_timer.timeout.connect(self.start_walk)

        # 主动聊天：随机 40~90 秒冒一句话
        self.chatter_timer = QTimer(self); self.chatter_timer.setSingleShot(True)
        self.chatter_timer.timeout.connect(self.idle_chatter)

        # T8/T9/T10 集成层初始化（实现分别在 pet_vision / pet_agent_link / pet_drag）
        self._init_drag_physics()      # T10：甩抛/重力/反弹
        self._init_vision()             # T8：截图哈希判闲置 → 视觉模型
        self._init_agent_link(APP_DIR)  # T9：外部 Agent 事件总线（默认关）

        # 提醒：喝水/久坐等周期性提醒统一由 custom_reminder_timers 管理
        # （分钟级循环定时器，成本≈0，静默模式也生效）
        self.custom_reminder_timers = {}   # idx -> QTimer

        # 每日单词推送：60s 巡检，未规划先选词落盘，到点分批弹小气泡卡（独立于入睡守卫）
        self._word_card = None            # 正在展示的回看词卡（None=没有）
        self._word_bubble = None          # 正在展示的分批小气泡卡
        self._word_warned = False         # 词库缺失时气泡只提示一次
        self._word_menu_action = None     # 托盘「今日单词」QAction（make_tray 后引用）
        self._app_start_ts = time.time()  # 启动 3 分钟内不推词，避免开机糊脸
        self.word_timer = QTimer(self)
        self.word_timer.setInterval(60 * 1000)
        self.word_timer.timeout.connect(self._word_tick)

        # 入睡状态机：空闲超时入睡（sleep_after_min），仅 normal 模式生效
        self.last_touch_ts = time.time()   # 最近一次用户互动时间戳
        self.sleep_check_timer = QTimer(self)
        self.sleep_check_timer.setInterval(5000)
        self.sleep_check_timer.timeout.connect(self._check_sleep)
        # 连续点击唤醒：2.5s 内点 3 次；超时清零计数
        self._wake_click_count = 0
        self._wake_click_timer = QTimer(self)
        self._wake_click_timer.setSingleShot(True)
        self._wake_click_timer.timeout.connect(self._reset_wake_clicks)
        self._sleep_pending = False        # True=正在播放入睡动画，播完落定 sleep 态

        self.walk_frame = 0
        self.walk_dir = 1       # 剧本主体朝向（镜像轮为 -1）
        self._walk_mir = False

        # 测试动作循环列表
        self.test_actions = list(ACTIONS.keys())
        self.test_index = 0

        # bounce 用：记录弹跳前的窗口位置（结束后还原）
        self._orig_y = None
        # 收尾淡出用
        self._fade_from = None
        self._fade_step = 0
        self._fade_total = 6
        # 遮罩缓存：按 QPixmap 对象 id 缓存 alpha 遮罩，避免动作每帧重复计算
        self._mask_cache = {}
        # 显示尺寸自适应：_loaded_h=已加载素材的高度；_last_screen=上次所在屏
        self._loaded_h = 0
        self._last_screen = None
        # T3 预缩放缓存：分批把缩放后的帧拼 strip 写盘（QTimer 驱动，不卡 UI）
        self._cache_timer = QTimer(self)
        self._cache_timer.setInterval(5)          # 每 5ms 拼一条 strip
        self._cache_timer.timeout.connect(self._cache_build_tick)
        self._cache_strips = []                   # 待写盘的 strip 分片
        self._cache_layout = {}                   # {strip 文件名: {帧名: [x,y,w,h]}}
        self._cache_strip_idx = 0
        self._cache_cdir = None                     # 本次写入的目标目录

        # AI 对话（未配置时自动回退内置文案）
        self.ai = PetAI(self.settings)
        self.chat_history = []        # 多轮对话上下文（本次运行内有效）
        self._chat_busy = False
        self._chat_worker = None
        self._parse_worker = None

        self.reload_sprites()
        if self.settings.get("pos_x") is not None:
            self.move(self.settings["pos_x"], self.settings["pos_y"])
        else:
            screen = self.current_screen().availableGeometry()
            self.move(screen.right() - self.width() - 120,
                      screen.bottom() - self.height() - 80)
        self._last_screen = self.current_screen()   # 跨屏检测的基线

        # 多屏：屏幕插拔后把小江钳回有效区域（副屏拔出时不丢猫）
        app = QApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._on_screens_changed)
            app.screenRemoved.connect(self._on_screens_changed)

        self.setup_reminders()
        self.apply_mode(self.settings["mode"], save=False)
        self.setup_word_push()   # 每日单词调度（默认开启；静默模式也生效）

    # ---------- 显示尺寸（上下限 + 多屏自适应 + DPI 感知） ----------
    def current_screen(self):
        """小江当前所在的屏幕；还没上屏时回落主屏"""
        scr = self.screen()
        if scr is None:
            scr = QApplication.primaryScreen()
        return scr

    def compute_display_height(self, screen=None):
        """按「当前屏可用高度 × 比例 × 用户体型系数」算显示高度（钳到 80~240）"""
        if screen is None:
            screen = self.current_screen()
        return display_height_for(screen, self.settings.get("height_factor", 1.0))

    def reload_sprites_if_size_changed(self):
        """重算显示高度，只有与已加载高度相差 ≥ H_RELOAD_DELTA 才真重载。

        重载要解码 500 帧（约 7s），跨屏/换屏时必须节流：同一屏内反复移动不该重载。
        """
        h = self.compute_display_height()
        if abs(h - self._loaded_h) < H_RELOAD_DELTA:
            log(f"[size] 重算高度 {h}px，与当前 {self._loaded_h}px 差异 <"
                f"{H_RELOAD_DELTA}px，跳过重载")
            return False
        self.reload_sprites()
        return True

    def _sync_screen_on_move(self):
        """被拖到另一块屏 → 按新屏可用高度重算尺寸（重载受节流保护）"""
        scr = self.screen()
        if scr is None or scr is self._last_screen:
            return
        self._last_screen = scr
        log(f"[screen] 小江移到 {scr.name()}，重算显示尺寸")
        self.reload_sprites_if_size_changed()

    def _on_screens_changed(self, *_args):
        """屏幕插拔：延后一拍处理（信号到达时屏幕对象可能已被析构）"""
        QTimer.singleShot(0, self._ensure_on_screen)

    def _ensure_on_screen(self):
        """副屏拔出后把小江钳回有效区域；已不在任何屏内则 recentre() 唤回"""
        try:
            g = self.geometry()
            scr = None
            for s in QApplication.screens():
                if s.availableGeometry().intersects(g):
                    scr = s
                    break
            if scr is None:              # 掉出所有屏 → 唤回
                log("[screen] 小江已不在任何屏幕内，唤回")
                self.recentre()
                self._last_screen = self.current_screen()
                return
            ag = scr.availableGeometry()
            nx = min(max(g.x(), ag.left()), max(ag.left(), ag.right() - g.width()))
            ny = min(max(g.y(), ag.top()), max(ag.top(), ag.bottom() - g.height()))
            if (nx, ny) != (g.x(), g.y()):
                self.move(nx, ny)
                log(f"[screen] 小江被钳回 {scr.name()} 可视区 ({nx},{ny})")
            if scr is not self._last_screen:
                self._last_screen = scr
                self.reload_sprites_if_size_changed()
        except Exception as e:
            log(f"[screen] 屏幕变化处理失败: {e}")

    # ---------- 素材加载（灵宠中心改高度后也会调用） ----------
    def _frame_names(self):
        """reload_sprites 会加载的全部帧文件名清单（缓存完整性校验用）。
        图集模式下帧清单来自索引（散帧目录可为空）"""
        idx = _load_atlas_index()
        if idx is not None:
            order = idx.get("order")
            if order and set(order) == set(idx["frames"].keys()):
                return list(order)
            return list(idx["frames"].keys())
        names = ["idle_open.png", "idle_blink.png",
                 "click_surprise.png", "click_happy.png"]
        for name in ACTIONS:
            i = 1
            while (SPRITES_DIR / f"{name}_{i:02d}.png").exists():
                names.append(f"{name}_{i:02d}.png")
                i += 1
        return names

    @staticmethod
    def _cache_signature(names):
        """源素材指纹：任一帧的 size/mtime 变了（比如重新编码）缓存即失效。
        图集模式下以图集文件 + 索引为指纹（散帧目录不再被读取）"""
        idx = _load_atlas_index()
        if idx is not None:
            try:
                parts = ["atlas"]
                st = ATLAS_INDEX_FILE.stat()
                parts.append(f"idx:{st.st_size}:{int(st.st_mtime)}")
                for f in sorted(ATLAS_DIR.glob("*.png")):
                    st = f.stat()
                    parts.append(f"{f.name}:{st.st_size}:{int(st.st_mtime)}")
                return "|".join(parts)
            except OSError:
                return None
        parts = []
        for n in names:
            try:
                st = (SPRITES_DIR / n).stat()
            except OSError:
                return None
            parts.append(f"{n}:{st.st_size}:{int(st.st_mtime)}")
        return "|".join(parts)

    def _cache_ready(self, cdir, names):
        """缓存目录可用 = manifest 指纹匹配 + 每个 strip 文件都在 + 覆盖全部帧"""
        try:
            with open(cdir / "manifest.json", encoding="utf-8") as f:
                man = json.load(f)
            if man.get("signature") != self._cache_signature(names):
                return False
            covered = set()
            for strip_file, rects in man.get("layout", {}).items():
                if not (cdir / strip_file).exists():
                    return False
                covered.update(rects.keys())
            return set(names) <= covered
        except Exception:
            return False

    def _load_cache_pixmaps(self, cdir, dpr):
        """从缓存 strip 图批量读回所有帧（每高度只需解码十几个文件）"""
        with open(cdir / "manifest.json", encoding="utf-8") as f:
            man = json.load(f)
        frames = {}
        for strip_file, rects in man["layout"].items():
            big = QPixmap(str(cdir / strip_file))
            for name, (x, y, w, hh) in rects.items():
                pm = big.copy(x, y, w, hh)
                pm.setDevicePixelRatio(dpr)       # 位图已是物理像素，补 DPR 标记
                frames[name] = pm
        return frames

    def _schedule_cache_build(self, cdir, items):
        """缓存未命中时，加载完成后把缩放好的帧分批拼 strip 写盘（后台，不卡 UI）。

        实测瓶颈是「每文件 ~6ms 的加载开销」而非解码/缩放，所以缓存按横幅图
        （sprite strip）组织：500 帧 → 十几个文件，二次启动解码量骤降。
        """
        self._cache_timer.stop()
        self._cache_cdir = cdir
        self._cache_layout = {}
        self._cache_strip_idx = 0
        # 按宽度上限 8192px 分片（规避 Qt 纹理宽度限制，同时控制单 tick 耗时）
        max_w = 8192
        self._cache_strips = []
        cur, cur_w = [], 0
        for name, pm in items:
            w = pm.width()
            if cur and cur_w + w > max_w:
                self._cache_strips.append(cur)
                cur, cur_w = [], 0
            cur.append((name, pm))
            cur_w += w
        if cur:
            self._cache_strips.append(cur)
        if self._cache_strips:
            self._cache_timer.start()

    def _cache_build_tick(self):
        """每次拼一条 strip 并写盘；写完收尾：落 manifest、清理旧高度缓存目录"""
        cdir = self._cache_cdir
        if cdir is None:
            self._cache_timer.stop()
            return
        if not self._cache_strips:
            # 全部写完：manifest + 清理旧高度目录
            try:
                sig = self._cache_signature(self._frame_names())
                if sig and self._cache_layout:
                    with open(cdir / "manifest.json", "w", encoding="utf-8") as f:
                        json.dump({"signature": sig,
                                   "layout": self._cache_layout}, f)
                self._prune_old_cache(cdir)
            except Exception as e:
                log(f"[cache] manifest 写入失败: {e}")
            self._cache_timer.stop()
            log(f"[cache] 预缩放缓存构建完成: {cdir}")
            return
        strip = self._cache_strips.pop(0)
        try:
            cdir.mkdir(parents=True, exist_ok=True)
            total_w = sum(pm.width() for _, pm in strip)
            hh = strip[0][1].height()
            canvas = QPixmap(total_w, hh)
            canvas.fill(Qt.transparent)
            painter = QPainter(canvas)
            x = 0
            rects = {}
            for name, pm in strip:
                painter.drawPixmap(x, 0, pm)
                rects[name] = [x, 0, pm.width(), pm.height()]
                x += pm.width()
            painter.end()
            fname = f"strip_{self._cache_strip_idx:04d}.png"
            self._cache_strip_idx += 1
            canvas.save(str(cdir / fname), "PNG")
            self._cache_layout[fname] = rects
        except Exception as e:
            log(f"[cache] strip 写盘失败: {e}")

    @staticmethod
    def _prune_old_cache(keep_dir):
        """只保留当前高度的缓存目录，防止磁盘膨胀。
        容忍删除失败（比如被占用）—— 多留一代只占几十 MB，不影响正确性"""
        try:
            for d in SPRITES_CACHE_DIR.glob("h*"):
                if d != keep_dir and d.is_dir():
                    shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    def _load_atlas_frames(self, phys):
        """图集冷加载：多线程解码横幅图（QImage 允许非 GUI 线程，PySide6 释放 GIL），
        主线程 copy() 切帧 + 缩放到物理高度，边解码边消费控制峰值内存。
        PNG 全量解码 ~2.4s 单线程 → 8 线程 ~0.5s。失败返回 None 走散帧回退"""
        idx = _load_atlas_index()
        if idx is None:
            return None
        strips = {}                                   # 图集文件 -> [(帧名, 矩形)]
        for name, (fname, x, y, w, hh) in idx["frames"].items():
            strips.setdefault(fname, []).append((name, x, y, w, hh))

        def decode(fname):
            r = QImageReader(str(ATLAS_DIR / fname))
            r.setAutoTransform(False)
            return fname, r.read()                    # QImage：非 GUI 线程安全

        frames = {}
        n_threads = min(8, os.cpu_count() or 4)
        try:
            with ThreadPoolExecutor(n_threads) as ex:
                futures = [ex.submit(decode, fn) for fn in strips]
                for fut in as_completed(futures):
                    fname, img = fut.result()
                    items = strips[fname]
                    if img is None or img.isNull():
                        log(f"[atlas] {fname} 解码失败，散帧回退")
                        return None
                    big = QPixmap.fromImage(img)     # QImage→QPixmap 必须在 GUI 线程
                    del img
                    for name, x, y, w, hh in items:
                        pm = big.copy(x, y, w, hh).scaledToHeight(
                            phys, Qt.TransformationMode.SmoothTransformation)
                        frames[name] = pm
                    del big
        except Exception as e:
            log(f"[atlas] 多线程解码异常，散帧回退: {e}")
            return None
        if len(frames) != len(idx["frames"]):
            log("[atlas] 切帧数与索引不符，散帧回退")
            return None
        return frames

    def reload_sprites(self):
        self._mask_cache.clear()
        h = self.compute_display_height()
        self._loaded_h = h
        dpr = self.devicePixelRatioF() or 1.0
        phys = int(round(h * dpr))               # 物理像素高度 = 缓存 key
        cdir = SPRITES_CACHE_DIR / f"h{phys}"
        names = self._frame_names()
        cached = None
        if self._cache_ready(cdir, names):
            log(f"[cache] 命中 h={phys}px 预缩放缓存，跳过全量解码")
            try:
                cached = self._load_cache_pixmaps(cdir, dpr)
            except Exception as e:
                log(f"[cache] 缓存读取失败，回退源图加载: {e}")
                cached = None
        atlas_frames = None                        # 未命中缓存时先试图集（19 文件）
        if cached is None:
            atlas_frames = self._load_atlas_frames(phys)
            if atlas_frames is not None:
                log(f"[atlas] 图集加载 {len(atlas_frames)} 帧")
        collected = []                           # 未命中时收集物理尺寸帧，供后台构建缓存

        def load(name):
            if cached is not None and name in cached:
                return cached[name]
            if atlas_frames is not None and name in atlas_frames:
                raw = atlas_frames[name]
            else:
                # 兜底：从散帧源图解码并缩放（无图集时的老路径）
                p = QPixmap(str(SPRITES_DIR / name))
                # 先按设备像素比缩到物理尺寸，再标回 DPR：逻辑尺寸仍是 h，
                # 位图按 h×dpr 提供 → 高 DPI 屏不会被 Qt 二次放大而发虚
                raw = p.scaledToHeight(phys,
                                       Qt.TransformationMode.SmoothTransformation)
            pm = QPixmap(raw)                    # 物理尺寸浅拷贝（dpr=1，拼 strip 用）
            pm.setDevicePixelRatio(dpr)
            collected.append((name, raw))
            return pm

        self.pix_open = load("idle_open.png")
        self.pix_blink = load("idle_blink.png")
        self.pix_surprise = load("click_surprise.png")
        self.pix_happy = load("click_happy.png")

        # 加载视频提取的新动作序列（帧清单来自索引/散帧探测，两种模式通用）
        self.action_frames = {}
        for name in ACTIONS:
            prefix = f"{name}_"
            frames = [load(n) for n in names
                      if n.startswith(prefix) and n[len(prefix):].rstrip(".png").isdigit()]
            if frames:
                self.action_frames[name] = frames
                log(f"加载动作序列 {name}: {len(frames)} 帧")
            else:
                log(f"[warn] 动作序列 {name} 无素材")

        # 散步序列 = pace 完整踱步剧本 + 镜像收尾（构造逻辑见 pet_walk.py）
        pace_frames = self.action_frames.get("pace", [])
        # 镜像走 QImage 层（transformed 位图配手工遮罩有平台坑，见 _build_mask）
        def _mir(pm):
            img = pm.toImage().transformed(QTransform().scale(-1, 1))
            out = QPixmap.fromImage(img)
            out.setDevicePixelRatio(pm.devicePixelRatioF())
            return out
        self.walk_seq, self.walk_seq_mir = pet_walk.build_walk_seq(pace_frames, _mir)
        log(f"散步序列: {len(self.walk_seq)} 帧（pace 剧本 + 镜像收尾）")

        self.set_frame(self.pix_open)
        self.adjustSize()
        # 缓存未命中 → 后台分批构建（不影响本次显示）
        if collected:
            self._schedule_cache_build(cdir, collected)

    @staticmethod
    def _build_mask(pm):
        """手工构建 1-bit 遮罩（pm.mask() 平台位图对镜像内容会被 Windows 错误裁切，见 tools/probe_mask_fix.py）"""
        img = pm.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        flat = QImage(img.size(), QImage.Format.Format_ARGB32)
        flat.fill(Qt.GlobalColor.black)
        qp = QPainter(flat)
        qp.drawImage(0, 0, img)
        qp.end()
        gray = flat.convertToFormat(QImage.Format.Format_Grayscale8)
        mono = gray.createMaskFromColor(0, Qt.MaskMode.MaskOutColor)  # 非纯黑→1
        return QBitmap.fromImage(mono)

    def set_frame(self, pm):
        """换帧统一入口：同时更新贴图和鼠标遮罩。
        遮罩让透明区域点击穿透——猫矩形窗口的空白角落不会挡住下面的软件。
        遮罩按 QPixmap 缓存，动作循环播放时不再每帧重复计算 alpha 遮罩。"""
        self.setPixmap(pm)
        mask = self._mask_cache.get(id(pm))
        if mask is None:
            mask = self._build_mask(pm)
            if mask is not None:
                self._mask_cache[id(pm)] = mask
        if mask is not None:
            self.setMask(mask)

    def name(self):
        return self.settings.get("pet_name", "小江")

    def _interval_ms(self, min_key, max_key, default_min, default_max):
        """读设置里的 [min,max] 秒区间，返回一个随机毫秒数（保证 min<=max）"""
        lo = max(1, int(self.settings.get(min_key, default_min)))
        hi = max(lo, int(self.settings.get(max_key, default_max)))
        return random.randint(lo, hi) * 1000

    def recentre(self):
        """回到当前所在屏中央偏下（猫走丢时用托盘一键唤回）"""
        screen = self.current_screen().availableGeometry()
        self.move(screen.center().x() - self.width() // 2,
                  screen.center().y() + screen.height() // 6)
        self.raise_()

    def moveEvent(self, event):
        """小江窗口任何移动（拖拽/散步/bounce）都同步气泡位置 + 检测跨屏"""
        super().moveEvent(event)
        if hasattr(self, "bubble") and self.bubble:
            self.bubble.follow((self.x(), self.y(), self.width()))
        self._sync_screen_on_move()

    def chatter(self):
        """随机冒一句：约 18% 概率是「当下时段」的时间问候，否则按性格加权选普通文案"""
        if random.random() < 0.18:
            g = self._time_greeting()
            if g:
                return g
        return self._personality_chatter()

    def _time_greeting(self):
        """返回当前时段应说的话；时段外返回 None（周末另有问候）"""
        now = datetime.now()
        if now.weekday() >= 5 and random.random() < 0.35:
            return random.choice(WEEKEND_GREETINGS)
        for sh, eh, texts in TIME_GREETINGS:
            if sh <= now.hour < eh:
                return random.choice(texts)
        return None

    def _personality_chatter(self):
        """按性格权重从文案池加权随机一条（未配置权重的类别默认权重 1）"""
        weights = PERSONALITIES.get(self.settings.get("personality"), {}).get("weights", {})
        pool = []
        for group, texts in CHATTER_GROUPS.items():
            w = weights.get(group, 1)
            for t in texts:
                pool.append((t, w))
        texts, ws = zip(*pool)
        return random.choices(texts, weights=ws, k=1)[0].format(name=self.name())

    # ---------- 新动作播放器 ----------
    def play_action(self, name):
        """播放一个动作序列；可被拖拽/点击/切模式打断"""
        frames = self.action_frames.get(name)
        if not frames:
            log(f"[warn] 动作 {name} 没有可用帧")
            return

        # 停止可能冲突的动画定时器
        for t in (self.blink_timer, self.unblink_timer, self.walk_timer,
                  self.behavior_timer, self.chatter_timer):
            t.stop()
        # 如果当前正在播放另一个动作，直接覆盖
        self.action_timer.stop()

        cfg = ACTIONS[name]
        self.state = "action"
        self.action_name = name
        self.action_idx = 0
        self.action_loops_left = 0 if cfg.get("loop") else max(1, cfg.get("loops", 1))
        self.set_frame(frames[0])
        interval = max(20, int(1000 / cfg["fps"]))
        self.action_timer.start(interval)
        log(f"播放动作 {name} fps={cfg['fps']} loop={cfg['loop']}")

    def action_step(self):
        # 点击 bounce：垂直位移循环
        if self.action_name == "_bounce":
            if self._bounce_idx >= len(self._bounce_seq):
                self.finish_action()  # 已在最后一帧 dy=0 还原 y
                return
            dy = self._bounce_seq[self._bounce_idx]
            self._bounce_idx += 1
            self.move(self.x(), (self._orig_y or self.y()) + dy)
            return

        # 收尾淡出：最后一帧 → idle_open，6 帧 × 50ms ≈ 0.3s
        if self.state == "fade" and self._fade_from is not None:
            self._fade_step += 1
            if self._fade_step >= self._fade_total:
                self._fade_from = None
                self._finish_to_idle()
                return
            ratio = self._fade_step / self._fade_total
            self.set_frame(self._make_blended(self._fade_from, self.pix_open, ratio))
            return

        # 普通动作序列
        if self.state != "action" or self.action_name is None:
            return
        frames = self.action_frames[self.action_name]
        self.action_idx += 1
        if self.action_idx >= len(frames):
            # 入睡动画播完：停在最后一帧并真正进入 sleep 态
            # （不走淡出回 idle，也不恢复 blink/behavior/chatter 等自动定时器）
            if self._sleep_pending and self.action_name == "sleep":
                self._sleep_pending = False
                self.action_timer.stop()
                self.action_name = None
                self.state = "sleep"
                self.set_frame(frames[-1])
                self.bubble.say("呼噜… Zzz…（拖动我或快速点三下叫醒）",
                                (self.x(), self.y(), self.width()), ms=3000)
                return
            cfg = ACTIONS[self.action_name]
            if self.action_loops_left > 1:        # 有限循环：再播一轮
                self.action_loops_left -= 1
                self.action_idx = 0
            elif cfg.get("loop"):                 # 无限循环（如呼吸）
                self.action_idx = 0
            else:
                self.finish_action()
                return
        self.set_frame(frames[self.action_idx])

    def _make_blended(self, pm1, pm2, ratio):
        """0..1 的 alpha 混合：ratio=0 -> pm1，ratio=1 -> pm2（结果沿用源的 DPR）"""
        from PySide6.QtGui import QPainter
        dpr = pm1.devicePixelRatioF() or 1.0
        out = QPixmap(pm1.size())     # 按物理像素分配
        out.setDevicePixelRatio(dpr)  # 逻辑尺寸仍是一帧那么大
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.scale(dpr, dpr)             # 位图是物理尺寸，绘制用逻辑坐标
        p.setOpacity(1.0 - ratio)
        p.drawPixmap(0, 0, pm1)
        p.setOpacity(ratio)
        p.drawPixmap(0, 0, pm2)
        p.end()
        return out

    def finish_action(self):
        """动作结束：根据情况启动淡出到 idle，或直接收尾"""
        self.action_timer.stop()
        name = self.action_name
        self.action_name = None

        # bounce 已在 step 里把 y 还原为 _orig_y；不淡出，直接走收尾
        # 其他动作最后一帧 → idle_open 做 6 帧淡出，消除"突切"
        if name and name != "_bounce" \
                and name in self.action_frames \
                and self.action_frames[name] \
                and self.settings["mode"] == "normal":
            last = self.action_frames[name][-1]
            if last.size() == self.pix_open.size():
                self._fade_from = last
                self._fade_step = 0
                self.state = "fade"
                self.action_timer.start(50)
                return
        self._finish_to_idle()

    def _finish_to_idle(self):
        """淡出完成后 / 无需淡出时调用：回到 idle 并排下一次行为"""
        self._orig_y = None  # bounce 位置记录用完即清
        self.state = "idle"
        self.set_frame(self.pix_open)
        if self.settings["mode"] != "normal":
            return
        self.schedule_next_blink()
        if self.settings["auto_walk"]:
            self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))
        self.chatter_timer.start(self._interval_ms("chat_min_sec", "chat_max_sec", 40, 90))
        self.schedule_next_auto_action()

    # ---------- 测试动作（按钮专用） ----------
    def test_action(self):
        """临时按钮：循环触发有素材的动作（自动跳过无素材的 recoil/spin 槽位）"""
        playable = [n for n in ACTIONS if n in self.action_frames]
        if not playable:
            return
        name = playable[self.test_index % len(playable)]
        self.test_index += 1
        self.play_action(name)
        label = ACTION_LABELS.get(name, name)
        self.bubble.say(f"{label}~", (self.x(), self.y(), self.width()), ms=1200)

    # ---------- 空闲自动触发动作 ----------
    def schedule_next_auto_action(self):
        """安排一次未来的随机动作；非 normal 模式 / 入睡态不排（间隔在灵宠中心可调）"""
        if self.state == "sleep" or self._sleep_pending:
            return  # 入睡中/已入睡：不再重排任何自动行为定时器
        if self.settings["mode"] != "normal":
            return
        self.auto_action_timer.start(self._interval_ms("action_min_sec", "action_max_sec", 10, 30))

    def maybe_auto_action(self):
        """空闲时按类别加权挑动作（30% 待机/10% 转向/40% 动作/20% 移动，防连续重复；详见 action_scheduler.py）"""
        if self.state == "sleep" or self._sleep_pending:
            return  # 入睡中/已入睡：睡眠后零自动行为
        if self.state != "idle" or self.settings["mode"] != "normal":
            self.schedule_next_auto_action()
            return
        # 随机池 = 有素材且 auto=True 的动作；两级加权调度（类别 → 类别内动作）
        pool = [n for n, c in ACTIONS.items()
                if c.get("auto", True) and n in self.action_frames]
        name = action_scheduler.pick_behavior(pool, getattr(self, "_last_auto", None))
        if not name:  # 待机（或池空）：本轮不播，仅重排下一次
            self.schedule_next_auto_action(); return
        self._last_auto = name; log(f"自动触发动作 {name}（加权调度）")
        self.play_action(name)

    # ---------- 提醒 ----------
    def setup_reminders(self):
        """根据设置启停提醒定时器；间隔为 0 即关闭。
        喝水/久坐等所有周期性提醒统一由自定义提醒（reminders）管理。"""
        self._setup_custom_reminders()

    def _setup_custom_reminders(self):
        """重建所有自定义提醒定时器（灵宠中心保存 / 快速添加时调用）
        支持三种 mode：
          - interval：每 N 分钟循环（once=True 则一次性，触发后自动停用）
          - daily：   每天 at HH:MM 触发（单次定时器，触发后再排明天）
          - weekly：  每周 weekday 的 at HH:MM 触发（触发后再排下周日）"""
        # 先全部停掉
        for t in self.custom_reminder_timers.values():
            t.stop()
        self.custom_reminder_timers.clear()
        for idx, r in enumerate(self.settings.get("reminders", [])):
            if not r.get("enabled", True):
                continue
            mode = r.get("mode", "interval")
            if mode in ("daily", "weekly"):
                at = r.get("at", "09:00")
                try:
                    hh, mm = map(int, at.split(":"))
                except Exception:
                    continue
                target = self._next_cycle_target(mode, r, hh, mm)
                if target is None:
                    continue
                now = datetime.now()
                delay_ms = max(1000, int((target - now).total_seconds() * 1000))
                t = QTimer(self)
                t.setSingleShot(True)
                t.timeout.connect(lambda i=idx: self._fire_recurring_reminder(i))
                t.start(delay_ms)
            else:
                mins = int(r.get("interval_min", 0))
                if mins <= 0:
                    continue
                t = QTimer(self)
                t.timeout.connect(lambda i=idx: self.fire_custom_reminder(i))
                t.start(mins * 60 * 1000)
            self.custom_reminder_timers[idx] = t

    @staticmethod
    def _next_cycle_target(mode, r, hh, mm):
        """daily/weekly 的下一次触发时刻 datetime；无法计算返回 None"""
        now = datetime.now()
        if mode == "daily":
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target
        # weekly：下一个 weekday（isoweekday 1=周一..7=周日）
        try:
            wd = int(r.get("weekday") or 0)
            if not 1 <= wd <= 7:
                return None
        except Exception:
            return None
        days_ahead = (wd - now.isoweekday()) % 7
        if days_ahead == 0:
            days_ahead = 7   # 今天已过该点 → 下周
        target = (now + timedelta(days=days_ahead)).replace(
            hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=7)
        return target

    def _fire_recurring_reminder(self, idx):
        """周期（daily/weekly）提醒触发：弹气泡后按周期重排下一次"""
        self.fire_custom_reminder(idx)
        reminders = self.settings.get("reminders", [])
        if idx >= len(reminders):
            return
        r = reminders[idx]
        if not r.get("enabled", True):
            return
        mode = r.get("mode")
        if mode == "daily":
            step_ms = 24 * 60 * 60 * 1000
        elif mode == "weekly":
            step_ms = 7 * 24 * 60 * 60 * 1000
        else:
            return
        # 重新排下一个周期
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda i=idx: self._fire_recurring_reminder(i))
        t.start(step_ms)
        self.custom_reminder_timers[idx] = t

    def fire_custom_reminder(self, idx):
        """触发第 idx 条自定义提醒（弹气泡）"""
        reminders = self.settings.get("reminders", [])
        if idx >= len(reminders):
            return
        r = reminders[idx]
        name = r.get("name", "提醒")
        # 名称含关键词的走专属文案池；其余用通用催办文案
        if "喝水" in name:
            msg = random.choice(WATER_TEXTS).format(name=self.name())
        elif any(k in name for k in ("起来", "久坐", "活动", "走走")):
            msg = random.choice(SIT_TEXTS).format(name=self.name())
        else:
            msgs = [
                f"该{name}啦喵~",
                f"{self.name()}提醒你：{name}",
                f"到点啦！该{name}了",
                f"叮咚~{name}时间到！",
                f"小江来催{name}啦~",
                f"别忘了{name}哦！",
            ]
            msg = random.choice(msgs)
        self.bubble.say(msg,
                        (self.x(), self.y(), self.width()), ms=5000)
        log(f"自定义提醒触发: {name}")
        # 一次性提醒：触发后自动停用（避免反复弹）
        if r.get("once"):
            r["enabled"] = False
            save_settings(self.settings)
            t = self.custom_reminder_timers.pop(idx, None)
            if t:
                t.stop()
            log(f"一次性提醒已完成，自动停用: {name}")

    # ---------- 快速提醒（L2 本地解析 → L3 LLM 解析 → 提示）----------
    def quick_reminder_input(self):
        """托盘菜单 / 灵宠中心入口：弹输入框，解析后入库
        解析链：本地 NLP-lite（L2）→ 失败则 LLM 解析（L3，需启用 AI）→ 再失败给提示"""
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getMultiLineText(
            self, "快速设置提醒",
            "用一句话描述（小江会试着听懂）：\n"
            "· 3分钟后提醒我喝水\n"
            "· 明天早上9点提醒交作业\n"
            "· 每周一晚上8点提醒开会\n"
            "· 每天9点提醒吃药\n"
            "· 15:30 提醒接孩子",
            ""
        )
        if not ok or not text.strip():
            return
        self.last_touch_ts = time.time()   # 用户成功提交了一条提醒
        t = text.strip()
        r = parse_reminder(t)
        if r:
            self._add_reminder_record(r)
            return
        # L2 听不懂 → 交给 L3（LLM），未启用 AI 则直接提示
        self._parse_via_llm(t)

    def _add_reminder_record(self, r):
        """把一条解析好的提醒入库并反馈气泡"""
        self.last_touch_ts = time.time()
        self.settings.setdefault("reminders", []).append(r)
        save_settings(self.settings)
        self._setup_custom_reminders()
        self.bubble.say(f"好的喵~{describe_reminder(r)}",
                        (self.x(), self.y(), self.width()), ms=4000)
        log(f"快速提醒入库: {describe_reminder(r)}")

    def _parse_via_llm(self, text):
        """L3 兜底：后台线程调 LLM 解析一句话"""
        if not (self.settings.get("ai_enabled") and self.settings.get("ai_api_key")):
            self.bubble.say(
                "没听懂喵~试试「30分钟后提醒我喝水」或「每天9点提醒吃药」",
                (self.x(), self.y(), self.width()), ms=4000)
            return
        self.bubble.say("唔…让小江想想喵~",
                        (self.x(), self.y(), self.width()), ms=1200)
        w = ReminderParseWorker(self.ai, text)
        w.result_ready.connect(self._on_llm_reminder)
        self._parse_worker = w     # 持有引用，防 GC
        w.start()

    def _on_llm_reminder(self, r):
        """L3 解析结果回调：入库或提示换说法"""
        self._parse_worker = None
        if r:
            self._add_reminder_record(r)
        else:
            self.bubble.say(
                "小江没听懂喵…换个说法，或去灵宠中心手动添加？",
                (self.x(), self.y(), self.width()), ms=4000)
            log(f"[reminder] L3 解析失败: 用户输入未识别")

    # ---------- 灵宠中心 ----------
    def open_center(self):
        dlg = PetCenter(self.settings, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            v = dlg.values()
            set_autostart(v.pop("autostart", False))   # 开关开机自启（注册表）
            old_name = self.settings.get("pet_name", "小江")
            height_changed = v["height_factor"] != self.settings.get("height_factor")
            self.settings.update(v)
            # 性格决定 AI 人设（persona 由性格自动生成；AI 任务细调留待后续）
            self.settings["ai_persona"] = build_persona(v["personality"], v["pet_name"])
            save_settings(self.settings)
            self.last_touch_ts = time.time()   # 用户完成一次设置交互
            self.ai = PetAI(self.settings)   # 刷新 AI 配置（含 key/模型/人设）
            if v.get("ai_enabled"):
                self.bubble.say("AI 已接入，双击我和我聊喵~",
                                (self.x(), self.y(), self.width()), ms=3000)
            if height_changed:
                self.reload_sprites()   # 换尺寸后重载素材
            # 换尺寸重载素材会显示 idle 睁眼帧；若猫正睡着，恢复睡眠帧
            if self._is_sleeping():
                self._sleep_pending = False
                self.action_timer.stop()
                self.action_name = None
                self.state = "sleep"
                self.set_frame(self.pix_blink)
            # 散步开关立即生效
            if not v["auto_walk"] and self.state == "walk":
                self.walk_timer.stop()
                self.state = "idle"
                self.set_frame(self.pix_open)
                self.schedule_next_blink()
            self.setup_reminders()
            self.setup_word_push()   # 每日单词：读取新设置重建调度（开/关/词量即时生效）
            self._apply_vision_settings()   # T8：主动行为开关/节奏即时生效
            # 只有真改名了才自我介绍，普通保存不打扰
            if v["pet_name"] != old_name:
                self.bubble.say(f"从今天起叫我 {self.name()} 喵~",
                                (self.x(), self.y(), self.width()))

    # ---------- 模式 ----------
    def apply_mode(self, mode, save=True):
        self.settings["mode"] = mode
        if save:
            save_settings(self.settings)
        # 动作播放器也纳入静默控制
        self.action_timer.stop()
        self.action_name = None
        if mode == "normal":
            # 从睡眠/入睡中恢复显示（清睡眠残留，避免 stuck 在 sleep）
            if self._is_sleeping():
                self._sleep_pending = False
                self._wake_click_count = 0
                self._wake_click_timer.stop()
            self.state = "idle"
            self.set_frame(self.pix_open)
            self.schedule_next_blink()
            self.chatter_timer.start(self._interval_ms("chat_min_sec", "chat_max_sec", 40, 90))
            if self.settings["auto_walk"]:
                self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))
            self.schedule_next_auto_action()   # 启动空闲自动动作循环
            self.sleep_check_timer.start(5000)  # 空闲超时入睡检测（normal 才入睡）
        else:  # silent：动画定时器全部停止，零 CPU（提醒仍生效）
            self.sleep_check_timer.stop()
            if self._is_sleeping():
                self._sleep_pending = False
                self._wake_click_count = 0
                self._wake_click_timer.stop()
            for t in (self.blink_timer, self.unblink_timer, self.react_timer,
                      self.walk_timer, self.behavior_timer, self.chatter_timer,
                      self.auto_action_timer):
                t.stop()
            self.bubble.hide()
            self.state = "idle"
            self.set_frame(self.pix_open)

    def toggle_auto_walk(self, on):
        self.settings["auto_walk"] = on
        save_settings(self.settings)
        if not on:
            self.walk_timer.stop()
            self.behavior_timer.stop()
            if self.state == "walk":
                self.state = "idle"
                self.set_frame(self.pix_open)
                self.schedule_next_blink()
        else:
            if self.settings["mode"] == "normal" and self.state == "idle":
                self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))

    # ---------- 眨眼（只在待机时发生） ----------
    def schedule_next_blink(self):
        self.blink_timer.start(self._interval_ms("blink_min_sec", "blink_max_sec", 3, 7))

    def do_blink(self):
        if self.state != "idle":
            return
        self.set_frame(self.pix_blink)
        self.unblink_timer.start(150)

    def undo_blink(self):
        if self.state == "idle":
            self.set_frame(self.pix_open)
            self.schedule_next_blink()

    # ---------- 入睡状态机（空闲超时入睡 / 点击/拖拽/双击唤醒）----------
    def _is_sleeping(self):
        """是否处于睡眠：已入睡 sleep 态，或正在播放入睡动画（sleep_pending）"""
        return self.state == "sleep" or self._sleep_pending

    def _reset_wake_clicks(self):
        """wake_click_timer 超时：连续点击计数清零（2.5s 内没凑够 3 次）"""
        self._wake_click_count = 0

    def _system_idle_sec(self):
        """距用户上次系统级键盘/鼠标输入的秒数；非 win32 或失败返回 0"""
        if sys.platform != "win32":
            return 0.0
        try:
            import ctypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                return 0.0
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return max(0, millis) / 1000.0
        except Exception:
            return 0.0

    def _check_sleep(self):
        """sleep_check_timer（5s/次）：满足条件则入睡。成本≈0"""
        if self.settings["mode"] != "normal":
            return
        if self.state == "sleep" or self._sleep_pending:
            return
        # AI 请求 / 提醒解析进行中 → 不入睡
        if self._chat_busy or self._parse_worker is not None:
            return
        # 散步 / 拖拽 / 动作播放中 → 稍后再查
        if self.state in ("walk", "drag", "action"):
            return
        try:
            mins = int(self.settings.get("sleep_after_min", 0) or 0)
        except Exception:
            mins = 0
        if mins <= 0:
            return
        touch_gap = time.time() - self.last_touch_ts
        sys_idle = self._system_idle_sec()
        if touch_gap >= mins * 60 or sys_idle >= mins * 60:
            self.go_sleep()

    def go_sleep(self):
        """进入睡眠：停止所有自动行为；有 sleep 素材先播入睡动画再落定"""
        if self.state == "sleep" or self._sleep_pending:
            return
        log("进入睡眠（空闲超时）")
        self.bubble.hide()
        self._wake_click_count = 0
        self._wake_click_timer.stop()
        for t in (self.blink_timer, self.unblink_timer, self.react_timer,
                  self.walk_timer, self.behavior_timer, self.chatter_timer,
                  self.auto_action_timer, self.action_timer):
            t.stop()
        if "sleep" in self.action_frames:
            self._sleep_pending = True
            self.play_action("sleep")   # 播完由 action_step 落到 sleep 态（停在末帧）
        else:
            # 没有入睡动画素材：直接进 sleep，显示闭眼/睁眼静止帧
            self.state = "sleep"
            self.set_frame(self.pix_blink)
            self.bubble.say("呼噜… Zzz…（拖动我或快速点三下叫醒）",
                            (self.x(), self.y(), self.width()), ms=3000)

    def wake_up(self):
        """唤醒：播 wake 动画（正常结束会淡出回 idle 并恢复自动行为）"""
        if not self._is_sleeping():
            return
        log("被唤醒")
        self._wake_click_count = 0
        self._wake_click_timer.stop()
        self._sleep_pending = False
        self.last_touch_ts = time.time()
        self.action_timer.stop()
        self.action_name = None
        if "wake" in self.action_frames:
            self.bubble.say("嗯？…我醒啦！", (self.x(), self.y(), self.width()), ms=1200)
            self.play_action("wake")   # 播完 finish_action → 淡出回 idle + 恢复自动定时器
        else:
            self.bubble.hide()
            self._finish_to_idle()

    # ---------- 每日英语单词推送（独立于入睡守卫） ----------
    def setup_word_push(self):
        """按设置启停每日单词调度：60s 巡检，09:00~20:30 间到点分批弹小气泡卡。
        静默模式沿用提醒语义：动画停、推送照常生效。"""
        self.word_timer.stop()
        self._word_warned = False   # 重新启用/重设时允许再次提示
        if not self.settings.get("word_enabled", True):
            return
        self.word_timer.start()
        self._refresh_word_menu()
        log(f"每日单词调度已启用 · 词量={self.settings.get('word_count', 10)}/天"
            f" · 每批{wp.BATCH_SIZE}词")

    def _word_pushed_today(self):
        """当天是否已有词可回看（至少推出过一批）"""
        return wp.any_pushed_today(wp.load_progress(WORDS_PROGRESS_FILE))

    def _refresh_word_menu(self):
        act = getattr(self, "_word_menu_action", None)
        if act is None:
            return
        try:
            act.setEnabled(self._word_pushed_today())
        except RuntimeError:      # 托盘/action 已被销毁
            self._word_menu_action = None

    def _word_card_visible(self):
        try:
            for w_ in (self._word_card, self._word_bubble):
                if w_ is not None and w_.isVisible():
                    return True
        except RuntimeError:        # 词卡已被销毁
            self._word_card = None
            self._word_bubble = None
        return False

    def _word_modal_busy(self):
        """聊天/设置等模态中，或词卡已开着 → 本次跳过、等下一窗口"""
        if self._word_card_visible():
            return True
        app = QApplication.instance()
        return app is not None and app.activeModalWidget() is not None

    def _word_tick(self):
        # 60s 巡检：未规划先选词落盘；到点且间隔足够则推下一批
        if not self.settings.get("word_enabled", True):
            return
        if time.time() - self._app_start_ts < 180:
            return
        if self._word_modal_busy():
            return
        prog = wp.load_progress(WORDS_PROGRESS_FILE)
        if not wp.pushed_today(prog):
            prog = self._plan_today_words(prog)
            if prog is None:
                return
        idx = wp.due_batch(prog)
        if idx is not None:
            self._push_word_batch(prog, idx)

    def _plan_today_words(self, prog):
        words = wp.load_words()
        if not words:
            if not self._word_warned:
                self._word_warned = True
                self.bubble.say("单词库没装上喵…（词库文件缺失）",
                                (self.x(), self.y(), self.width()), ms=3500)
                log("[word] 词库缺失/为空，每日单词调度停止")
                self.word_timer.stop()
            return None
        try:
            count = max(5, min(20, int(self.settings.get("word_count", 10))))
        except (TypeError, ValueError):
            count = 10
        _day_words, new_prog = wp.plan_words(words, prog, None, count)
        wp.save_progress(WORDS_PROGRESS_FILE, new_prog)
        log(f"[word] 今日词单已规划 · {len(_day_words)} 词")
        return new_prog

    def _push_word_batch(self, prog, idx):
        """弹一批小气泡卡：睡着先唤醒；落 batch_done/last_push_ts 进度"""
        batches = wp.batches_for(prog["words"])
        if idx >= len(batches):
            return
        prog = dict(prog)
        prog["batch_done"] = idx + 1
        prog["last_push_ts"] = time.time()
        wp.save_progress(WORDS_PROGRESS_FILE, prog)
        self._refresh_word_menu()
        was_sleeping = self._is_sleeping()
        if was_sleeping:
            self._word_wake_look()
        bubble = wp.WordBubble(batches[idx], idx + 1, len(batches))
        self._word_bubble = bubble
        bubble.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        bubble.finished.connect(lambda _res: self._on_word_card_closed(was_sleeping))
        bubble.show()
        if self.isVisible():
            g = bubble.frameGeometry()
            g.moveCenter(self.geometry().center())
            g.moveTop(self.geometry().top() - g.height() - 12)
            bubble.move(g.topLeft())
            bubble.clamp_to_screen()
        log(f"[word] 推送第 {idx + 1}/{len(batches)} 批 · {len(batches[idx])} 词")

    def _show_word_card(self, words, title, was_sleeping=False):
        if self._word_card_visible():
            return
        card = wp.WordCardDialog(words, title=title)
        self._word_card = card
        card.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        card.finished.connect(lambda _res: self._on_word_card_closed(was_sleeping))
        card.show()
        if self.isVisible():
            g = card.frameGeometry()
            g.moveCenter(self.geometry().center())
            card.move(g.topLeft())
            card.clamp_to_screen()
        log(f"[word] 词卡已弹出 · {title} · {len(words)} 词")

    def _on_word_card_closed(self, was_sleeping):
        self._word_card = None
        self._word_bubble = None
        if was_sleeping:
            self._restore_sleep_after_word()

    def _word_wake_look(self):
        """睡着被推送：唤醒表现（播 wake；无素材回 idle），随后弹词卡"""
        self._wake_click_count = 0
        self._wake_click_timer.stop()
        self._sleep_pending = False
        self.action_timer.stop()
        self.action_name = None
        if "wake" in self.action_frames:
            self.bubble.say("喵！起来学今天的单词~",
                            (self.x(), self.y(), self.width()), ms=1600)
            self.play_action("wake")   # 播完淡出回 idle；词卡关闭后再睡回
        else:
            self.bubble.hide()
            self.state = "idle"
            self.set_frame(self.pix_open)

    def _restore_sleep_after_word(self):
        """词卡关闭后若原是睡着：直接置睡眠帧/静止，不重启任何自动定时器"""
        self._sleep_pending = False
        self.action_timer.stop()
        self.action_name = None
        for t in (self.blink_timer, self.unblink_timer, self.react_timer,
                  self.walk_timer, self.behavior_timer, self.chatter_timer,
                  self.auto_action_timer):
            t.stop()
        self._wake_click_count = 0
        self._wake_click_timer.stop()
        self.state = "sleep"
        frames = self.action_frames.get("sleep")
        self.set_frame(frames[-1] if frames else self.pix_blink)
        log("[word] 词卡关闭，恢复睡眠画面")

    def open_today_words(self):
        prog = wp.load_progress(WORDS_PROGRESS_FILE)
        if not wp.any_pushed_today(prog):
            self.bubble.say("今天还没推过单词喵~",
                            (self.x(), self.y(), self.width()), ms=3000)
            return
        self.last_touch_ts = time.time()
        self._show_word_card(wp.words_pushed_so_far(prog),
                             title="今日单词", was_sleeping=False)

    # ---------- 主动聊天 ----------
    def idle_chatter(self):
        if self.state == "sleep" or self._sleep_pending:
            return  # 入睡中/已入睡：不主动开口，也不重排下一次闲聊定时器
        if self.state == "idle" and self.settings["mode"] == "normal":
            # 启用 AI 时，约 1/3 概率小江自己主动开口（异步，不卡 UI）
            if self.settings.get("ai_enabled") and random.random() < 0.35:
                self.proactive_ai()
            else:
                self.bubble.say(self.chatter(),
                                (self.x(), self.y(), self.width()))
        # 无论上一轮有没有说上话，都排下一次（保持节奏）
        if self.settings["mode"] == "normal":
            self.chatter_timer.start(self._interval_ms("chat_min_sec", "chat_max_sec", 40, 90))

    # ---------- AI 聊天（异步，不卡 UI）----------
    def _launch_chat(self, cue, thinking_ms=800, record_cue=True):
        """统一异步聊天入口：后台线程请求，结果由 _on_ai_result 显示。
        record_cue=False 用于小江自己主动开口（不把"提示词"记进对话历史）。"""
        if self._chat_busy:
            return False
        self._chat_busy = True
        if thinking_ms:
            self.bubble.say("唔…让我想想", (self.x(), self.y(), self.width()), ms=thinking_ms)
        history_for_call = self.chat_history
        if record_cue:
            self.chat_history.append({"role": "user", "content": cue})
            self.chat_history = self.chat_history[-12:]
            history_for_call = self.chat_history[:-1]
        self._chat_worker = ChatWorker(self.ai, cue, history_for_call)
        self._chat_worker.result_ready.connect(self._on_ai_result)
        self._chat_worker.finished.connect(lambda: setattr(self, "_chat_busy", False))
        self._chat_worker.start()
        return True

    def ask_ai(self, user_text):
        """用户主动聊天（双击猫咪 / 托盘菜单）"""
        if not user_text:
            return
        self.last_touch_ts = time.time()   # 收到用户文字 → 算一次互动
        if not self._launch_chat(user_text, 800):
            self.bubble.say("等等，我还没想完喵~", (self.x(), self.y(), self.width()), ms=1200)

    def proactive_ai(self):
        """小江自己想说话：结合当前时段情境主动开口（不再出现'16点说晚上好'）"""
        now = datetime.now()
        wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        time_hint = f"{now.month}月{now.day}日{wd} {now.hour:02d}:{now.minute:02d}"
        cue = (
            f"现在是{time_hint}。请结合当前时段，用一句话可爱地、"
            "带点傲娇地对主人说点什么（早安/下午好/晚上好/夜深了等要对应时段）。"
            "别提问，不超过30字。"
        )
        self._launch_chat(cue, thinking_ms=0, record_cue=False)

    def _on_ai_result(self, ans):
        if not ans or ans.startswith("__ERR__"):
            log(f"[ai] 调用失败，回退内置文案: {ans}")
            ans = self.chatter()          # 未配置/出错 -> 回退内置文案
        else:
            self.chat_history.append({"role": "assistant", "content": ans})
            self.chat_history = self.chat_history[-12:]
        if len(ans) > 60:
            ans = ans[:60] + "…"
        self.bubble.say(ans, (self.x(), self.y(), self.width()), ms=4000)

    def open_chat_input(self):
        dlg = ChatInputDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            text = dlg.text()
            if text:
                self.last_touch_ts = time.time()   # 用户真的发了一条消息
                self.ask_ai(text)

    # ---------- 被点击反应 ----------
    def react_stage(self, stage):
        if stage == 1:
            self.set_frame(self.pix_surprise)
            self.react_timer.start(500)
        elif stage == 2:
            self.set_frame(self.pix_happy)
            self.bubble.say(self.chatter(),
                            (self.x(), self.y(), self.width()))
            self.react_timer.start(900)
        else:
            self.state = "idle"
            self.set_frame(self.pix_open)
            self.schedule_next_blink()
            if self.settings["auto_walk"]:
                self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))

    def next_react(self):
        # react_timer 每响一次推进一个阶段：惊讶(1) → 开心(2) → 结束(3)
        self.react_stage(getattr(self, "_react", 0) + 1)

    def start_react(self):
        # 点击反馈动作池：只挑已加载素材的动作，加权随机（recoil 4 / spin 4 / walk_circle 2）
        # 池为空时回退到 squash & stretch 开心跳（无新素材也能动）
        self.bubble.say(self.chatter(),
                        (self.x(), self.y(), self.width()), ms=1500)
        pool = [n for n in ("recoil", "spin", "walk_circle")
                if n in self.action_frames]
        if pool:
            weights = {"recoil": 4, "spin": 4, "walk_circle": 2}
            act = random.choices(pool, weights=[weights[n] for n in pool], k=1)[0]
            log(f"点击反馈动作: {act}")
            self.play_action(act)
            return
        self.play_bounce()

    def play_bounce(self):
        """点击开心跳：squash & stretch + 垂直位移，无需 recoil 素材也能给动画反馈。
        8 帧 ~0.48s：蓄力压扁→上升→顶点→落地压扁→回正。"""
        if self.state == "action" and self.action_name == "_bounce":
            return
        self.action_timer.stop()
        self._orig_y = self.y()
        self.state = "action"
        self.action_name = "_bounce"
        # 8 帧位移序列（相对原 y，负=上跳），单位 px
        self._bounce_seq = [-14, -10, -6, -2, 4, 10, 14, 0]
        self._bounce_idx = 0
        self.set_frame(self.pix_happy)
        self.action_timer.start(60)  # 8 × 60ms ≈ 0.48s
        log("播放点击 bounce（squash & stretch + 垂直位移）")

    # ---------- 散步 ----------
    def start_walk(self):
        if self.settings["mode"] != "normal" or not self.settings["auto_walk"]:
            return
        if self.state == "action":   # 动作播放中不打断，散步延后
            self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))
            return
        self.state = "walk"
        self.blink_timer.stop(); self.unblink_timer.stop()
        # 50% 概率整体镜像：先左后右 / 先右后左，避免每次都同一路线
        self._walk_mir = random.random() < 0.5
        self.walk_dir = -1 if self._walk_mir else 1   # 剧本主体朝右走（镜像轮朝左）
        self.walk_frame = 0
        self.walk_timer.start(42)   # 24fps 素材原速

    def walk_step(self):
        seq = self.walk_seq_mir if self._walk_mir else self.walk_seq
        k = self.walk_frame
        if k >= len(seq):
            self._finish_walk()
            return
        # 窗口位移 = 预计算的画布内质心位移 × 缩放比（跟随：猫走窗走、猫停窗停）
        dx = pet_walk.PACE_DX[k] * (-1 if self._walk_mir else 1)
        dx = round(dx * self.width() / 512.0)
        if dx:
            screen = self.current_screen().availableGeometry()
            nx = self.x() + dx
            if nx < screen.left() or nx + self.width() > screen.right():
                self.walk_frame = len(seq)   # 撞屏幕边缘：提前结束散步
            else:
                self.move(nx, self.y())
        self.set_frame(seq[k])
        self.walk_frame += 1
        if self.walk_frame >= len(seq):
            self._finish_walk()

    def _finish_walk(self):
        """散步结束：回到 idle（序列末帧已是坐姿，与 idle 平滑衔接）"""
        self.walk_timer.stop()
        self.state = "idle"
        self.set_frame(self.pix_open)
        self.schedule_next_blink()
        self.behavior_timer.start(self._interval_ms("walk_min_sec", "walk_max_sec", 12, 30))

    # ---------- 右键菜单 ----------
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        center = QAction(f"{self.name()} · 灵宠中心（点击设置）", menu)
        center.triggered.connect(self.open_center)
        menu.addAction(center)
        menu.addSeparator()

        normal = QAction("正常模式（眨眼 + 散步）", menu)
        normal.setCheckable(True)
        normal.setChecked(self.settings["mode"] == "normal")
        normal.triggered.connect(lambda: self.apply_mode("normal"))

        silent = QAction("省电静默模式（零动画）", menu)
        silent.setCheckable(True)
        silent.setChecked(self.settings["mode"] == "silent")
        silent.triggered.connect(lambda: self.apply_mode("silent"))

        auto = QAction("自动散步", menu)
        auto.setCheckable(True)
        auto.setChecked(self.settings["auto_walk"])
        auto.triggered.connect(lambda checked: self.toggle_auto_walk(checked))

        menu.addAction(normal)
        menu.addAction(silent)
        menu.addAction(auto)
        menu.addSeparator()

        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(lambda: QApplication.instance().quit())
        menu.addAction(quit_action)

        menu.exec(event.globalPos())


def make_tray(pet):
    """系统托盘图标 + 右键菜单：唤回屏幕、模式切换、灵宠中心、退出"""
    icon = QIcon(str(SPRITES_DIR / "idle_open.png"))
    tray = QSystemTrayIcon(icon)
    tray.setToolTip(f"{pet.name()} · BabyCat")

    menu = QMenu()
    center = QAction("唤回屏幕中央", menu)
    center.triggered.connect(pet.recentre)
    pet_center = QAction("灵宠中心", menu)
    pet_center.triggered.connect(pet.open_center)
    chat_action = QAction("和TA聊天…", menu)
    chat_action.triggered.connect(pet.open_chat_input)
    quick_action = QAction("⏰ 快速提醒…（输入'30分钟后提醒我喝水'）", menu)
    quick_action.triggered.connect(pet.quick_reminder_input)
    word_action = QAction("📖 今日单词", menu)
    word_action.triggered.connect(pet.open_today_words)
    word_action.setEnabled(pet._word_pushed_today())
    pet._word_menu_action = word_action

    normal = QAction("正常模式", menu)
    normal.triggered.connect(lambda: pet.apply_mode("normal"))
    silent = QAction("省电静默模式", menu)
    silent.triggered.connect(lambda: pet.apply_mode("silent"))

    quit_action = QAction("退出", menu)
    quit_action.triggered.connect(lambda: QApplication.instance().quit())

    menu.addAction(center)
    menu.addAction(pet_center)
    menu.addAction(chat_action)
    menu.addAction(quick_action)
    menu.addAction(word_action)
    menu.addSeparator()
    menu.addAction(normal)
    menu.addAction(silent)
    menu.addSeparator()
    menu.addAction(quit_action)

    tray.setContextMenu(menu)
    # 单击托盘图标 = 唤回
    tray.activated.connect(lambda reason: pet.recentre()
                           if reason == QSystemTrayIcon.ActivationReason.Trigger
                           else None)
    tray.show()
    return tray


def acquire_single_instance_lock():
    """Windows 命名互斥量防双开。返回句柄（保持引用，否则锁失效）；
    已在运行时返回 None。"""
    if sys.platform != "win32":
        return "non-windows"  # 非 Windows 无锁（自用项目，无所谓）
    # 开发/测试用：当互斥量因强制 kill 残留时，设环境变量 BABYCAT_BYPASS_MUTEX=1 可跳过
    if os.environ.get("BABYCAT_BYPASS_MUTEX") == "1":
        log("[dev] 跳过单实例互斥量检查")
        return 1
    import ctypes
    ERROR_ALREADY_EXISTS = 183
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "BabyCat_SingleInstance")
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    lock = acquire_single_instance_lock()
    if lock is None:
        app = QApplication(sys.argv)
        QMessageBox.information(
            None, "BabyCat",
            "小江已经在你的桌面上啦，不要再开一只喵~")
        return

    install_crash_hook()
    log(f"启动 · PySide6={__import__('PySide6').__version__}")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("BabyCat")

    # 暗色玻璃主题：统一设置面板 / AI 聊天 / 提醒弹窗 / 消息框样式
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    except Exception:
        pass
    app.setStyleSheet(DIALOG_QSS)

    # 同步应用图标到所有弹窗标题栏（设置面板、聊天、提醒）
    icon_path = BASE_DIR / "assets" / "icon.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    settings = load_settings()
    # 旧配置迁移：water_min/sit_min → 并入自定义提醒列表（在 PetWindow 构造前做，
    # 保证初始化定时器时用的就是迁移后的 reminders）
    migrate_legacy_reminders(settings)
    # 旧配置升级 / 新安装：ai_persona 为空时按「性格」自动生成人设
    if not (settings.get("ai_persona") or "").strip():
        settings["ai_persona"] = build_persona(
            settings.get("personality", "粘人"), settings.get("pet_name", "小江"))
    pet = PetWindow(settings)
    pet.show()

    tray = make_tray(pet)  # 必须保持引用，否则托盘被回收

    test_btn = None
    if TEST_ACTION_BUTTON:
        test_btn = TestButton(pet)
        test_btn.show()

    log(f"运行中 · 名字={settings['pet_name']} "
        f"高度={pet.compute_display_height()}px 系数={settings['height_factor']} "
        f"模式={settings['mode']}")
    exit_code = app.exec()
    pet.stop_agent_link()   # T9：优雅停轮询线程（daemon 兜底，正常走这）
    log(f"退出 · code={exit_code}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
