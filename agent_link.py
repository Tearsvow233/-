# -*- coding: utf-8 -*-
"""Agent Link 事件总线（T9）。

外部 Agent（Claude / Cursor / IDE 插件等）往
``<config_dir>/agent-events/<agent>.jsonl`` 追加一行 JSON，
本模块用 byte-offset tail 读取并归一为 6 态（thinking / working /
attention / error / idle / sleeping），通过回调通知订阅者。

设计原则：
- 纯逻辑层，**禁 import PySide6**（可被 tests / tools 直接 import）
- 零网络、零端口、零 SDK；本地文件追加，跨进程安全
- 事件合法性边界严格：坏 JSON / 超长行 / 未知字段 → log + 跳过
- 线程安全：轮询线程 + 状态聚合在 Lock 内；callback 由调用者自行负责线程切换
- 资源回收：``stop()`` 设置 stop event 并 join 线程（最多 2s）

事件 schema（两种写法皆可）：
    {"ts": 1730000000, "agent": "claude", "state": "thinking"}      # 直接给 6 态之一
    {"ts": 1730000000, "agent": "claude", "event": "tool_start"}     # 语义事件，按 _EVENT_TO_STATE 归一
"""
import json
import threading
import time
from pathlib import Path

# ---------- 常量 ----------

# 6 态（与 docs/AgentLink需求.md §1 一致；外部可见）
STATES = ("thinking", "working", "attention", "error", "idle", "sleeping")

# 语义事件 → 6 态 的归一映射
_EVENT_TO_STATE = {
    # thinking
    "thinking": "thinking", "process_start": "thinking", "llm_request": "thinking",
    # working
    "working": "working", "tool_start": "working", "tool_use": "working", "writing": "working",
    # attention
    "attention": "attention", "user_input": "attention", "permission": "attention",
    # error
    "error": "error", "fail": "error", "crash": "error",
    # idle
    "idle": "idle", "done": "idle", "ready": "idle",
    # sleeping
    "sleeping": "sleeping", "process_end": "sleeping", "shutdown": "sleeping",
}

# 多 agent 聚合优先级：值越大越"抢眼"，最后胜出
STATE_PRIORITY = {
    "error": 5, "attention": 4, "working": 3,
    "thinking": 2, "idle": 1, "sleeping": 0,
}

# 防御性上限
MAX_LINE_BYTES = 64 * 1024          # 单行不超过 64KB
MAX_FILE_BYTES = 32 * 1024 * 1024   # 单文件不超过 32MB（防日志爆炸）

DEFAULT_STALE_SEC = 60.0            # 某 agent N 秒无新事件 → 回退 idle
DEFAULT_POLL_SEC = 0.5              # 轮询间隔


# ---------- 工具 ----------

def _log(msg):
    """与 main.py 的 log 同名 fallback；不依赖 main。"""
    print(f"[agent_link] {msg}")


def normalize_event(obj):
    """把一条 JSON 解析后的 dict 归一为 6 态之一；归一失败返回 None。

    支持两种写法：
      - ``{"state": "thinking"}`` 直接给状态
      - ``{"event": "tool_start"}`` 给事件名，按 ``_EVENT_TO_STATE`` 映射
    """
    if not isinstance(obj, dict):
        return None
    st = obj.get("state")
    if isinstance(st, str) and st in STATES:
        return st
    ev = obj.get("event")
    if isinstance(ev, str):
        return _EVENT_TO_STATE.get(ev)
    return None


# ---------- 内部状态 ----------

class _AgentState:
    """单个 agent 的内部状态：offset、最新事件时间、最新归一态。"""
    __slots__ = ("offset", "last_ts", "last_state")

    def __init__(self, offset=0):
        self.offset = offset
        self.last_ts = 0.0
        self.last_state = "idle"


# ---------- 读取器 ----------

class AgentLink:
    """事件总线读取器。

    用法::

        link = AgentLink(config_dir, poll_sec=0.5, stale_sec=60.0)
        link.set_callback(lambda state, agents: ...)   # agents: {name: (state, ts)}
        link.start()                                   # 启动 daemon 线程
        # ... 跑着 ...
        link.stop()                                    # 优雅停

    callback 参数：
      - state (str): 当前聚合的 6 态之一
      - agents (dict): 各 agent 详细状态 ``{name: (state, ts)}``

    callback 触发的时机是**聚合态发生迁移时**（与上一次不同），不是每个 poll 都触发。
    callback 跑在 daemon 线程内，调用方需要自己负责切到主线程（用 Qt signal / QTimer.singleShot）。
    """

    def __init__(self, config_dir, poll_sec=DEFAULT_POLL_SEC,
                 stale_sec=DEFAULT_STALE_SEC, callback=None, log=_log):
        self.config_dir = Path(config_dir)
        self.events_dir = self.config_dir / "agent-events"
        self.poll_sec = max(0.05, float(poll_sec))
        self.stale_sec = max(0.05, float(stale_sec))
        self.log = log
        self._callback = callback
        self._lock = threading.Lock()
        self._states = {}            # agent_name -> _AgentState
        self._stop_evt = threading.Event()
        self._thread = None
        self._last_emitted = "idle"  # 去重用
        self._initialized = False    # 区分「启动时已存在」与「运行中新出现」的文件

    # ---------- 公共 API ----------

    def set_callback(self, cb):
        """注册/替换状态变更回调。"""
        with self._lock:
            self._callback = cb

    def get_state(self):
        """同步获取当前聚合态（线程安全）。"""
        with self._lock:
            self._apply_stale_locked(time.time())
            return self._aggregate_locked()

    def get_agents(self):
        """同步获取各 agent 详细状态快照 ``{name: (state, ts)}``。"""
        with self._lock:
            now = time.time()
            self._apply_stale_locked(now)
            return {n: (s.last_state, s.last_ts) for n, s in self._states.items()}

    def start(self):
        """启动后台轮询线程。重复调用 no-op。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        try:
            self.events_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.log(f"创建 {self.events_dir} 失败：{e}")
            return
        # 首次启动：初始化所有现有 .jsonl 的 offset（**不读取历史**——只关注启动后新增）
        try:
            for p in self.events_dir.glob("*.jsonl"):
                name = p.stem
                try:
                    off = p.stat().st_size
                except OSError:
                    off = 0
                with self._lock:
                    self._states[name] = _AgentState(offset=off)
        except OSError as e:
            self.log(f"扫描 {self.events_dir} 失败：{e}")
        self._thread = threading.Thread(target=self._loop, name="AgentLink", daemon=True)
        self._thread.start()
        self.log(f"已启动，监听 {self.events_dir}（poll {self.poll_sec}s, stale {self.stale_sec}s）")

    def stop(self, join_timeout=2.0):
        """发停止信号并等线程退出。幂等。"""
        self._stop_evt.set()
        t = self._thread
        if t is not None:
            t.join(timeout=join_timeout)
            if t.is_alive():
                self.log("停止超时，线程仍在运行")
            self._thread = None
        self.log("已停止")

    def is_running(self):
        return self._thread is not None and self._thread.is_alive()

    # ---------- 内部 ----------

    def _apply_stale_locked(self, now):
        """把超时的 agent 标记为 idle。调用方持锁。"""
        for st in self._states.values():
            if st.last_state != "idle" and (now - st.last_ts) > self.stale_sec:
                st.last_state = "idle"

    def _aggregate_locked(self):
        """多 agent 聚合：取优先级最高的非 idle。调用方持锁。"""
        best = ("idle", -1)
        for st in self._states.values():
            prio = STATE_PRIORITY.get(st.last_state, 0)
            if prio > best[1]:
                best = (st.last_state, prio)
        return best[0]

    def _read_one(self, path, st):
        """从 path 的 st.offset 处读新增行；返回归一出的状态列表。"""
        out = []
        try:
            cur_size = path.stat().st_size
        except OSError:
            return out
        # 轮转/截断：文件变小 → 重置 offset 到 0
        if cur_size < st.offset:
            self.log(f"{path.name} 大小缩小（旧 {st.offset} → 新 {cur_size}），按轮转处理")
            st.offset = 0
        # 防御：单文件过大 → 重置 offset
        if cur_size > MAX_FILE_BYTES:
            self.log(f"{path.name} 超过 {MAX_FILE_BYTES} 字节，重置 offset=0")
            st.offset = 0
        try:
            with open(path, "rb") as f:
                f.seek(st.offset)
                data = f.read()
                st.offset += len(data)
        except FileNotFoundError:
            return out
        except OSError as e:
            self.log(f"读取 {path.name} 失败：{e}")
            return out
        for raw in data.splitlines():
            if not raw:
                continue
            if len(raw) > MAX_LINE_BYTES:
                self.log(f"{path.name} 有 {len(raw)} 字节的过长行，已跳过")
                continue
            try:
                obj = json.loads(raw.decode("utf-8", errors="replace"))
            except (ValueError, UnicodeDecodeError) as e:
                self.log(f"{path.name} 坏 JSON：{e}")
                continue
            norm = normalize_event(obj)
            if norm is None:
                continue
            st.last_ts = time.time()
            st.last_state = norm
            out.append(norm)
        return out

    def _poll_once(self):
        """单次扫描 + 读 + 聚合 + 触发 callback。"""
        try:
            current_files = {p.stem: p for p in self.events_dir.glob("*.jsonl")}
        except OSError as e:
            self.log(f"扫描 {self.events_dir} 失败：{e}")
            return
        with self._lock:
            # 1) 新文件 → 初始化
            for name in (set(current_files) - set(self._states)):
                # 运行中首次发现的：从头读（offset=0），不然会漏掉启动后到首次 poll 之间写入的内容
                off = 0 if self._initialized else current_files[name].stat().st_size
                self._states[name] = _AgentState(offset=off)
                if self._initialized:
                    self.log(f"发现新 agent：{name}")
            self._initialized = True
            # 2) 文件被删 → 清状态
            for name in (set(self._states) - set(current_files)):
                del self._states[name]
                self.log(f"agent {name} 文件已移除")
            # 3) 每个文件读新增
            for name, path in current_files.items():
                self._read_one(path, self._states[name])
            # 4) TTL 回退
            self._apply_stale_locked(time.time())
            # 5) 聚合 + 触发回调（去重）
            agg = self._aggregate_locked()
            snapshot = {n: (s.last_state, s.last_ts) for n, s in self._states.items()}
            if agg != self._last_emitted:
                cb, self._last_emitted = self._callback, agg
            else:
                cb = None
        if cb is not None:
            try:
                cb(agg, snapshot)
            except Exception as e:
                # callback 自身的异常：log 但不杀线程
                self.log(f"回调异常：{type(e).__name__}: {e}")

    def _loop(self):
        while not self._stop_evt.is_set():
            try:
                self._poll_once()
            except Exception as e:
                # 任何意外：log，绝不静默
                self.log(f"轮询异常：{type(e).__name__}: {e}")
            self._stop_evt.wait(self.poll_sec)
