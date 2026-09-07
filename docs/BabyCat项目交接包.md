# BabyCat 项目交接与协作包

> 目标读者：拿到这份文档的人，以及**他们的 AI Agent**。
> 用途：让任何一个人（或 Agent）在 10 分钟内理解 BabyCat 是什么、做到哪一步了、接下来该做什么、以及这个环境的坑在哪。
> 生成时间：2026-09-07　|　项目根目录：`D:\agent\BabyCat`

---

## 0. 一页速览

| 项 | 内容 |
|---|---|
| 是什么 | Windows **桌面宠物**应用，主角是布偶猫"小江"，常驻桌面、不占任务栏 |
| 技术栈 | Python 3.13 + **PySide6 6.11.2**，2D 序列帧动画，PyInstaller 单文件打包 |
| 代码规模 | `main.py` 2428 行 + `word_push.py` 333 + `ai_chat.py` 312 + `reminder_parser.py` 225 ≈ **3298 行** |
| 素材 | `assets/sprites/` **500 张 PNG，135 MB**（单帧 720×720 / 1024×1024） |
| 完成度 | 约 **92%**，功能完整可用；剩余为体验打磨与扩展项 |
| 当前状态 | 尺寸自适应刚实现完（**待验收**）；素材三步优化待开工 |

---

## 1. 项目全貌

### 1.1 文件地图

```
D:\agent\BabyCat\
├── main.py                 # 主程序：窗口/动画/状态机/提醒/设置面板/托盘（唯一大文件）
├── word_push.py            # 每日单词推送：选词算法 + 词卡窗口
├── ai_chat.py              # AI 对话（免费大模型，OpenAI 兼容协议）
├── reminder_parser.py      # 提醒文本解析
├── settings.json           # 用户配置（⚠️ 内含真实 API Key，见 §7）
├── BabyCat.spec            # PyInstaller 打包配置（资源内嵌，见 §6.5）
├── build.bat               # 一键重打包
├── assets/
│   ├── sprites/            # 500 张序列帧 PNG
│   ├── words/cet4_core.json# 四级核心词库 2607 词
│   └── concept/            # 角色概念图
├── docs/                   # 需求与方案文档（本文件在此）
├── tools/                  # 测试与素材处理脚本（非 pytest，直接 python 运行）
└── output/                 # 文档流水线产物、竞品参考源码（clones）
```

### 1.2 已实现功能

- **序列帧动作系统**：9 种基础动作 + 2 种复合动作，24fps，动作间有过渡衔接
- **入睡状态机**：系统空闲检测（`GetLastInputInfo`）触发，呼吸动画，点击唤醒
- **点击随机互动池**：随机动作 + 随机话术
- **AI 对话**：双击聊天，回复跟随宠物名
- **AI 提醒 L1–L3**：久坐 / 作息 / 自定义提醒
- **每日单词推送**：空闲时弹词卡；睡着被推 → 唤醒教词 → 再睡回
- **灵宠中心**：集中设置面板（已做弹窗自适应，无横向滚动、自动夹屏）
- **系统托盘**：完整菜单，含"📖今日单词"
- **尺寸自适应**（新）：上下限 80–240px + 多屏跟随 + DPI 感知

### 1.3 常用命令

```bash
# 运行（解释器已装 PySide6 6.11.2）
C:/Users/zhq/.workbuddy/binaries/python/versions/3.13.12/python.exe main.py

# 语法检查
...python.exe -m py_compile main.py

# 测试（tools/ 下是普通脚本，不是 pytest）
...python.exe tools/dev_smoke.py
...python.exe tools/qa_extra_smoke.py
...python.exe tools/test_word_push.py
...python.exe tools/test_chat_input_title.py

# 打包（onefile，约 178 MB）
build.bat
```

---

## 2. 本次对话沉淀的决策

### 2.1 竞品调研：dsh-pet 系列

调研了两个仓库（关系：**上游 + 桌面移植**）：

| | PC2005-cloud/dsh-pet（上游） | MerZlin/dsh-pet-indesktop（桌面版） |
|---|---|---|
| 形态 | DeepSeek Harness Web 里的**浏览器插件** | PySide6 **独立桌面应用** |
| Python | 9 文件 / 1104 行，几乎全是**素材生产脚本** | **77 文件 / 36,338 行** |
| 核心资产 | `prompts/` 提示词配方 + ffmpeg 抠像管线 + **97 个动作** | 桌面移植 + 物理交互 + 主动行为 + Agent 联动 |
| 测试 | — | **74 文件 / 1154 用例**，产品∶测试 ≈ 1.14∶1，三平台 CI |

**值得抄的 5 点**
1. **架构红线写成测试断言**（`tests/test_architecture.py`）：纯逻辑层禁 `import PySide6`、window 私有面跨模块访问零命中、`window.py` 行数预算 4300 只许降不许涨
2. **Agent Link 文件事件总线**：外部程序往 `<config>/agent-events/<agent>.jsonl` 追加一行 JSON，宠物用 byte-offset tail 读，归一为六态（thinking/working/attention/error/idle/sleeping）驱动动画。**零网络、零端口、零 SDK**
3. **素材"目录即配置"**：`assets/characters/<id>/videos/{idle,turn,move,click,drag,random,events}` + manifest 覆盖 + 外部目录自动发现 → 加角色零改代码
4. **动作权重调度**：30% 待机 / 10% 转向 / 40% 动作 / 20% 移动 + `exclude` 防连续重复
5. **proactive 主动行为**：截图 → 感知哈希比对判闲置 → 视觉模型 → 主动搭话（比只看"有没有输入"高一个维度）

**千万别抄的**：设置对话框 4791 行单文件；`except Exception` 182 处其中 **66 处直接 `pass`**；为"多开互撞"手写 seqlock + 共享内存 ring（1464 行，默认关闭，典型过度工程）；README 86 KB 堆砌且段落重复。

### 2.2 优化清单（按 ROI 排序）

| 优先级 | 项 | 现状 | 目标 |
|---|---|---|---|
| **P0** | 素材瘦身 | 500 帧 135 MB，单帧 720/1024（显示仅 100–240px） | 512 规范 → ~63 MB，内存 −75% |
| **P0** | 素材生产链 | 11 个动作全靠手工抽帧 | 提示词配方 + ffmpeg 管线，动作可批量生产 |
| **P1** | 架构红线测试 | 无 | 给 `main.py` 加行数预算 + 分层断言 |
| **P1** | 测试套件化 + CI | `tools/` 临时脚本，无 CI | pytest 化 + GitHub Actions |
| **P1** | 权重调度 / 多角色 | 纯随机池 / 只有一只猫 | 加权随机 / 目录即配置 |
| **P2** | proactive 主动行为 | 只有空闲检测 | 截图 + 感知哈希 + 视觉模型 |
| **P2** | Agent Link | 无 | JSONL 事件总线 |
| **P2** | 拖拽物理手感 | 基础 press/move | 甩抛 + 弹弓 + 反弹 |

### 2.3 已拍板：显示尺寸上下限（**代码已实现，待验收**）

| 决策 | 取值 |
|---|---|
| 下限 `MIN_PET_H` | **80 px**（再小看不清五官） |
| 上限 `MAX_PET_H` | **240 px**（4K 屏也不喧宾夺主） |
| 自适应基准 | `round(当前屏可用高度 × 0.11)` → 1080p≈118、1440p≈158、4K≈237 |
| 用户微调 | 相对系数 `height_factor`，**0.75 ~ 1.25**，默认 1.0 |
| 最终公式 | `h = clamp(round(屏高 × 0.11 × factor), 80, 240)` |

完整需求与验收基线见 `docs/宠物尺寸自适应需求.md`。实现位置：`main.py` 221–330（常量/迁移）、591/844（设置 UI）、1131–1224（多屏 + DPI + 节流）。

### 2.4 素材三步走（已拍板，未开工）

1. **源图降到 512 规范** —— 先备份 `assets/sprites`，再批量重编码（135 MB → ~63 MB）
2. **图集化 sprite sheet** —— 500 散文件合并为按动作分组的图集，减少冷启动文件 IO
3. **预缩放缓存** —— 首次启动后按当前高度缓存小图，二次启动目标 **<1s**（现状 7.4s）

> 实测提醒：降分辨率**省不了多少启动时间**（7.4s → 6.3s），因为瓶颈是 500 次文件打开 + 解码。要治冷启动得靠图集化或缓存。别把两件事混为一谈。

---

## 3. 待办清单（给接手 Agent 的任务表）

| # | 任务 | 优先级 | 验收标准 |
|---|------|--------|----------|
| T1 | **验收尺寸自适应** | 高 | 任何屏/任何系数下高度 ∈ [80,240]；副屏边界与唤回按副屏算；拔出副屏能钳回；150% 缩放不发虚；跨屏重载受节流（差 ≥4px 才重载） |
| T2 | 素材降到 512 规范 | 高 | 先备份；500 帧重编码完成；体积 ≤ 70 MB；肉眼无糊 |
| T3 | 图集化 sprite sheet | 中 | 500 散文件 → 图集；冷启动下降；动作播放无破图 |
| T4 | 预缩放缓存 | 中 | 二次启动 < 1s；改尺寸后缓存自动失效重建 |
| T5 | 架构红线测试 | 中 | `main.py` 行数预算断言 + 纯逻辑层禁 Qt 的断言就位 |
| T6 | pytest 化 + CI | 中 | `tools/` 脚本转为 pytest 用例；GitHub Actions 跑通 |
| T7 | 动作权重调度 | 低 | 加权随机 + 防重复；动作分布可统计验证 |
| T8 | proactive 主动行为 | 低 | 截图 + 感知哈希判闲置 → 主动搭话；进程名白名单保隐私 |
| T9 | Agent Link 事件总线 | 低 | JSONL 追加写 + tail 读取 + 六态归一；外部脚本可驱动 |
| T10 | 拖拽物理手感 | 低 | 甩抛 + 反弹 |

---

## 4. 给接手 Agent 的启动提示词（复制即用）

```
你是本项目的开发助手。请先完整阅读以下三份文档，再开工：
1. D:\agent\BabyCat\docs\BabyCat项目交接包.md   （项目全貌、决策、待办、环境坑）
2. D:\agent\BabyCat\docs\宠物尺寸自适应需求.md  （当前在做的任务，含验收基线）
3. D:\agent\BabyCat\docs\每日单词需求.md        （最近完成的模块，作代码风格参考）

环境：Python 用 C:/Users/zhq/.workbuddy/binaries/python/versions/3.13.12/python.exe
（已装 PySide6 6.11.2）。测试脚本在 tools/ 下，用 python 直接运行，不是 pytest。
改完必须：py_compile 通过 + 现有测试无回归 + 回报改动（文件+函数+行号）。

本次任务：<从待办清单 §3 里指定一项>

纪律：最小变更，不顺手重构；不修改素材文件除非任务明确要求；
截图类验证禁止使用 QT_QPA_PLATFORM=offscreen（会渲染成方框乱码）。
```

---

## 5. 项目约定（写代码前先看）

- **最小变更原则**：只改任务必需的代码，不顺手重构、不顺手改风格
- **暗色玻璃 UI**：所有对话框沿用全局 `DIALOG_QSS`，新增控件保持视觉一致
- **弹窗自适应**：新建对话框要按内容算尺寸、禁横向滚动、`showEvent` 里夹回屏幕（`word_push.py` 的 `clamp_to_screen()` 可直接复用）
- **不吞异常**：禁止 `except Exception: pass`（竞品 66 处这么干，是反面教材）
- **日志**：用 `log()` 输出，日志在 `logs/`
- **配置兼容**：改设置项要能迁移旧 `settings.json`，不能让老用户启动报错

---

## 6. 环境与已知坑（血泪清单）

| # | 坑 | 解法 |
|---|---|---|
| 6.1 | **PowerShell 工具输出为空**（连 `Test-Path` 都无回显） | 全程用 **Bash**，别指望 PowerShell |
| 6.2 | **沙箱对 `$HOME` 的写入不跨命令持久**：装到 `C:\Users\zhq\...` 的 venv 下一条命令就没了 | 需要临时 venv 就建到**工作区内**（如 `output/<id>/working/venv`） |
| 6.3 | **offscreen 截图全是方框（tofu）** | 需要真实渲染时**禁止**设 `QT_QPA_PLATFORM=offscreen` |
| 6.4 | **ghproxy 镜像 502**；直连 GitHub 反而能通 | 直接 `git clone https://github.com/...` |
| 6.5 | **PyInstaller onefile 资源内嵌**，`dist/assets/...` 下没有散落文件，误判为"打包失败" | 用日志/冒烟验证，不要按 dist 目录结构判断成功；词库已打进 exe（体积 +142 KB 可印证） |
| 6.6 | **文档转 docx 的环境陷阱**：`setup-html-to-docx.sh` 按 Unix 路径找 `$VENV/bin/python`，而 Windows 的 venv 是 `Scripts/python.exe` → 脚本反复删建、静默失败 | 绕开脚本：`python -m venv` 建到工作区 → `pip install --only-binary=:all:` → `PYTHONPATH=<plugin>/skills/html-to-docx/scripts <venv>/Scripts/python.exe -m html_to_docx convert in.html -o out.docx` |
| 6.7 | 冷启动 `reload_sprites()` 约 **7.4 秒**（500 帧解码） | 跨屏重算必须节流；真正解法是图集化或预缩放缓存 |

---

## 7. ⚠️ 安全提醒（分享前必做）

`settings.json` 里存着**真实的 AI API Key**（`ai_api_key` 字段，智谱 glm-4-flash）。分享本仓库或 `settings.json` 前：

1. 删除或脱敏 `ai_api_key`
2. 检查 `logs/` 里是否有 key 泄漏
3. 若已外泄，去控制台**吊销并重新生成**

（本交接包不含任何密钥。）

---

## 8. 本次对话时间线索引

| 阶段 | 产出 |
|---|---|
| 灵宠中心弹窗适配 | 禁横滚 + 按内容算宽 + showEvent 夹屏 |
| 聊天框标题 BugFix | 删除硬编码"和小江聊天"，`ChatInputDialog` 与宠物名解耦；同步完成项目盘点（约 92%） |
| 每日单词推送 | 需求逐项拍板 → `word_push.py` + `cet4_core.json`(2607 词) → QA 两轮（修 P1 夹屏失效）→ 打包 |
| 项目展示文档 | `BabyCat项目展示.docx`（封面+目录+7 章+8 图） |
| 竞品调研 | 克隆分析 dsh-pet 两个仓库，产出优化清单 |
| 尺寸自适应 | 方案拍板（80–240 + 自适应 + 相对系数）→ **代码已实现，待验收** |

---

## 9. 一句话总结

BabyCat 是一个**功能完整、可日常使用**的桌面宠物，当前的价值洼地不在"加功能"，而在**素材工程化**（体积极度过剩 + 无法批量生产）与**工程可信度**（测试、CI、架构红线）。前者决定它能长多大，后者决定别人是否相信它能长多大。
