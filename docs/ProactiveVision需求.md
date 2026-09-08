# 主动观察（proactive vision）需求

> T8 · 2026-09-08 · 状态：已实现 v1

## 1. 背景

现有主动聊天（`idle_chatter` → `proactive_ai`）只知道"现在几点"，
不知道"主人在干什么"。T8 升级为：**截图 → 感知哈希比对判闲置 →
视觉模型看一眼 → 主动搭话**，让搭话内容和主人真实状态相关
（"又在肝代码" / "该休息了"），而不是随机时段问候。

## 2. 隐私红线（本功能的第一设计原则）

1. **默认关闭**（`proactive_vision: False`），需在灵宠中心手动开启，且必须已启用 AI
2. **进程白名单**：只有前台进程命中 `vision_process_whitelist` 才允许把截图送模型；
   空白名单 = 永不上传。白名单默认只含浏览器/编辑器等常见开发应用
3. **闲置探测只用 9×8 灰度缩略图**（72 字节，不含任何可读信息）；
   只有确认闲置 + 白名单通过后才截全图
4. 全图发送前等比缩到 1024px 宽、JPEG 70 质量，只送当前这一次，不落盘、不留存
5. 提示词明令"不复述画面内容、不提问"
6. **冷却**：搭话一次后默认 30 分钟内不再触发（无论成败），防骚扰 + 防失败重试风暴

## 3. 架构（与 T9/T10 同构：纯逻辑层 + 薄集成层）

```
proactive_vision.py        ← 纯逻辑（禁 PySide6）
  dhash()                    9×8 灰度字节 → 64bit dHash
  hamming()                  哈希距离
  IdleDetector               闲置判定小状态机（边沿触发 + 冷却）
  process_allowed()          进程白名单（大小写不敏感，自动补 .exe）
ai_chat.py
  PetAI.reply_vision()       OpenAI 兼容多模态消息体（text + image_url）
main.py（集成层）
  foreground_process_path()  ctypes 取前台进程路径（零新依赖，仅 Windows）
  _grab_gray_thumb()         当前屏 → 9×8 灰度（QScreen.grabWindow）
  _grab_jpeg_b64()           当前屏 → ≤1024px JPEG base64
  _on_vision_tick()          观察/决策主流程（guard 链）
  _on_vision_result()        气泡展示
```

## 4. 参数（settings.json，均可灵宠中心改）

| 键 | 默认 | 说明 |
|---|---|---|
| `proactive_vision` | `false` | 总开关 |
| `vision_idle_min` | `10` | 画面+人静止多少分钟才触发 |
| `vision_check_sec` | `60` | 观察节拍（每次截一张缩略图） |
| `vision_cooldown_min` | `30` | 搭话后冷却 |
| `vision_process_whitelist` | 见下 | 允许被观察的前台应用 |
| `ai_vision_model` | `""` | 视觉模型名，留空回落 `ai_model` |

默认白名单：chrome / msedge / firefox / code / idea64 / pycharm64 /
devenv / notepad / obsidian / typora / explorer

## 5. 触发条件（guard 链，全部满足才发请求）

1. `proactive_vision` 且 `ai_enabled` 均开
2. 未入睡、未入睡等待、非拖拽/飞行态
3. 无进行中的视觉/聊天调用（防重入）
4. 不在冷却期
5. 距上次摸猫 ≥ `vision_idle_min`（人闲置）
6. **边沿触发**：画面连续 `vision_idle_min*60/vision_check_sec` 帧基本不变
   （从"动"到"静"的那一刻触发一次，持续静止不重复触发）
7. 前台进程命中白名单

失败路径：任一 guard 不满足 → 本拍直接跳过，不重试、不报错弹窗；
模型调用失败 → log 后静默，等冷却后下一轮。

## 6. 验收

- `tools/test_proactive_vision.py`：38 项断言（dHash/汉明/边沿触发/冷却/白名单/请求体/无 Qt 依赖）
- `tests/test_proactive_vision.py`：pytest 适配版（CI）
- `py_compile main.py ai_chat.py proactive_vision.py` 通过

## 7. 后续可选（v2）

- 观察结果写进 AI 对话历史（目前一次性气泡，不留上下文）
- 多屏支持（目前只看宠物所在屏）
- 白名单 UI 换成带勾选的列表（现在是逗号分隔文本框）
