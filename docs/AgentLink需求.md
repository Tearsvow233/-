# Agent Link 事件总线 — 需求定稿

> 定位：让 BabyCat 感知外部 Agent 工具（Claude/Cursor/IDE 插件等）的运行状态，
> 并把"对方在思考/干活/出错"映射到宠物的动作上。
> 状态：✅ 方案已与用户确认（基础架构沿用交接包 §2.1.2 竞品方案）

## 1. 已定决策

| 维度 | 决定 |
|---|---|
| 通信介质 | **本地文件** `<config_dir>/agent-events/<agent>.jsonl`，外部程序 append 一行 JSON |
| 方向 | **单向**：外部 → BabyCat（宠物不写回，避免误改） |
| 网络/端口 | **零网络、零端口、零 SDK**（任何 Agent 都能用，零依赖） |
| 读取方式 | **byte-offset tail**（不锁文件、不阻塞写者） |
| 归一目标态 | **6 态**：`thinking` / `working` / `attention` / `error` / `idle` / `sleeping` |
| 事件 schema | 两套兼容写法：直接 `{"state": "thinking"}` 或语义事件 `{"event": "tool_start"}` 归一映射 |
| 多 agent | **聚合**：监听整个 `agent-events/` 目录；按优先级取最"抢眼"状态（`error > attention > working > thinking > idle > sleeping`） |
| 状态过期 | 某 agent `stale_sec` 秒无新事件 → 自动回退为 `idle`（默认 60s） |
| 轮询频率 | 默认 500ms（足够灵敏，对磁盘 IO 几乎无感） |
| 错误边界 | 坏 JSON / 超长行 / 文件丢失 → log + 跳过；**轮询线程永不死** |
| 线程模型 | daemon 线程跑轮询；通过 Python 调用向主线程发信号（Qt signal 是线程安全的） |
| 默认启用 | **关闭**（`agent_link_enabled=False`）。不引入未要求的功能 |

## 2. 事件 schema

**直接状态（推荐，简单）**：
```json
{"ts": 1730000000, "agent": "claude", "state": "thinking"}
```

**语义事件（自动归一）**：
```json
{"ts": 1730000000, "agent": "claude", "event": "tool_start"}
```

字段说明：
- `ts`（可选）：事件时间戳（Unix epoch 秒），缺省用文件 mtime
- `agent`（可选）：agent 标识，缺省用文件名 stem
- `state` / `event`：二选一，详见上方映射表
- 其余字段忽略（向前兼容）

归一映射（`_EVENT_TO_STATE`）：
| 事件 | → 态 | 事件 | → 态 |
|---|---|---|---|
| `thinking` / `process_start` / `llm_request` | `thinking` | `error` / `fail` / `crash` | `error` |
| `working` / `tool_start` / `tool_use` / `writing` | `working` | `idle` / `done` / `ready` | `idle` |
| `attention` / `user_input` / `permission` | `attention` | `sleeping` / `process_end` / `shutdown` | `sleeping` |

## 3. 集成要点

- **模块**：`agent_link.py`（纯逻辑，**禁 import PySide6**，可被 tests/tools 直接 import）
- **配置项**（在 `DEFAULT_SETTINGS` 加）：
  - `agent_link_enabled`（默认 False）
  - `agent_link_config_dir`（默认 = settings.json 所在目录）
  - `agent_link_poll_ms`（默认 500）
  - `agent_link_stale_sec`（默认 60）
  - `agent_link_to_action`（dict：6 态 → 动作名，默认见 §4）
- **main.py 集成**：在 `main()` 中 `pet.show()` 之后创建 `AgentLink`，callback 通过 `pet.agent_state_signal.emit(state, snapshot)` 通知主线程（PetWindow 的 slot 决定做什么）
- **生命周期**：`app.aboutToQuit` 信号触发 `link.stop()`，确保线程回收
- **灵宠中心**：在「行为」分组下加开关 + stale_sec 滑块（v1 不做，等 T8 收尾时一起）
- **托盘**：暂不暴露

## 4. 6 态 → 动作映射（v1 默认值）

| 态 | 动作 | 备注 |
|---|---|---|
| `thinking` | `spin` | 抬手+歪头+转圈，"在想事情" |
| `working` | `pace` | 左右踱步，"在干活" |
| `attention` | `recoil` | 后仰站起，"哎呀叫我？" |
| `error` | `spin` + 气泡 | 转圈 + 气泡说"它好像遇到问题了" |
| `idle` | （不动作） | 让现有 idle 调度接管 |
| `sleeping` | （不动作） | 让现有 sleep 状态机接管（避免与 T1 入睡逻辑冲突） |

> 用户可在 settings 里覆盖 `agent_link_to_action` 映射（不暴露 UI，v1）。

## 5. 范围外（v1 明确不做）

- 灵宠中心 UI 配置项（只读 settings，不做交互）
- T8 proactive 视觉感知
- 事件回放 / 历史回看
- 加密 / 签名 / 鉴权（本地文件，无外部攻击面）
- Windows inotify 替代（用轮询足够，v1 不引入新依赖）
- 多 agent 分角色显示（v1 聚合为单一状态）

## 6. 验收基线

- `py_compile agent_link.py` 通过
- `python tools/test_agent_link.py` 退出码 0，覆盖：
  - 6 态归一（直接 state + 事件名）
  - 未知事件 / 坏 JSON / 超长行 / 缺字段 全部优雅跳过
  - 字节 offset 在重复读取间稳定
  - TTL/超时回退 idle
  - 文件被删 / 重新创建 → 状态被正确回收
  - 多文件多 agent 聚合优先级（error 压过 working）
- `pytest tests/test_agent_link.py` 跑通（沿用 T6 的 subprocess 模式）
- `tools/dev_smoke.py` 不回归
- T1–T7 既有功能零回归
- 不引入任何新第三方依赖（纯标准库）

## 7. 文件清单

| 路径 | 类型 | 说明 |
|---|---|---|
| `docs/AgentLink需求.md` | 本文件 | 需求定稿 |
| `agent_link.py` | 新增 | 事件总线读取器（纯逻辑） |
| `tools/test_agent_link.py` | 新增 | 独立验收脚本 |
| `tests/test_agent_link.py` | 新增 | pytest 包装（子进程跑 tools 脚本） |
| `main.py` | 改 | 加 DEFAULT_SETTINGS 5 项 + 启动/停止 + 信号-槽 |
