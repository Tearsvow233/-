# -*- coding: utf-8 -*-
"""T9 Agent Link 的 Qt 集成层（从 main.py 拆出，T5 行数预算红线）。

外部 Agent 往 <config_dir>/agent-events/<agent>.jsonl 追加事件，
AgentLink 轮询线程聚合成 6 态 → 通过 Qt Signal 派发到主线程 → 切动作/弹气泡。

修复记录（2026-09-08）：此前 main.py 只声明了信号和槽但从未实例化/启动
AgentLink（功能实际未生效），本 Mixin 的 _init_agent_link 补齐接线。
"""
import traceback

from agent_link import AgentLink


class AgentLinkMixin:
    """PetWindow 的外部 Agent 联动能力。宿主需提供：
    agent_state Signal(str, dict)（在 PetWindow 类上声明，Signal 必须
    落在 QObject 子类上）/ settings / action_frames / state /
    play_action() / bubble / x() / y() / width()
    """

    def _init_agent_link(self, config_dir):
        """启动 AgentLink 轮询（默认关；开着时读 <config_dir>/agent-events/*.jsonl）。"""
        from main import log
        s = self.settings
        if not s.get("agent_link_enabled", False):
            return
        # 轮询线程在 daemon 里触发，emit() 跨线程安全；slot 在主线程跑
        self.agent_state.connect(self.on_agent_state)
        try:
            self._agent_link = AgentLink(
                config_dir,
                poll_sec=max(0.1, s.get("agent_link_poll_ms", 500) / 1000),
                stale_sec=max(5, s.get("agent_link_stale_sec", 60)),
                callback=lambda state, agents: self.agent_state.emit(state, agents),
            )
            self._agent_link.start()
            log(f"[agent_link] 已启动，监听 {config_dir / 'agent-events'}")
        except Exception:
            # 总线挂了不影响宠物本体（红线：不吞异常 → 记日志）
            log(f"[error] AgentLink 启动失败:\n{traceback.format_exc()}")

    def stop_agent_link(self):
        """进程退出前优雅停止轮询线程。"""
        link = getattr(self, "_agent_link", None)
        if link is not None:
            try:
                link.stop()
            except Exception:
                pass

    # ---------- T9：Agent Link 状态切换 ----------
    def on_agent_state(self, state, agents):
        """AgentLink 信号槽：把外部 Agent 聚合态映射到动作。
        跑在主线程（Qt signal-slot 跨线程自动派发）。
        idle / sleeping 不动 —— 留给现有调度器 / 入睡状态机。
        """
        from main import log
        if state in ("idle", "sleeping"):
            return
        mapping = self.settings.get("agent_link_to_action") or {}
        action = mapping.get(state)
        if not action:
            return
        if action not in self.action_frames:
            log(f"[agent_link] 映射动作 {action} 不可用（无帧或未加载）")
            return
        # 不打断用户主动操作（drag / 拖拽中 / 反应链）
        if self.state in ("drag", "react"):
            return
        log(f"[agent_link] {state} → 动作 {action}")
        self.play_action(action)
        if state == "error" and agents:
            who = "、".join(agents.keys())[:30] or "外部 agent"
            try:
                self.bubble.say(f"{who} 好像遇到问题了…",
                                (self.x(), self.y(), self.width()), ms=3000)
            except Exception as e:
                log(f"[agent_link] 气泡失败：{e}")
