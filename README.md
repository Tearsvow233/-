# BabyCat 桌面宠物 🐱

> 一只叫"小江"的布偶猫，常驻 Windows 桌面，不占任务栏，会走路、会睡觉、会跟你聊天、会提醒你喝水。

![status](https://img.shields.io/badge/status-v1.0--rc-success)
![python](https://img.shields.io/badge/python-3.13-blue)
![qt](https://img.shields.io/badge/Qt-PySide6%206.11-green)

---

## 它能做什么

- **序列帧动作**：9 种基础动作 + 2 种复合动作，24fps，过渡衔接
- **会入睡**：你长时间不操作，它会打瞌睡；点一下就醒
- **会搭话**：双击打开聊天框，AI 用"小江"的人格回复
- **会催你**：久坐、作息、自定义三类提醒
- **每日单词**：空闲时主动弹词卡；睡着了会先把你唤醒再教
- **灵宠中心**：统一的设置面板，自适应尺寸 + 多屏跟随
- **尺寸自适应**：80–240px 区间自动取，按屏高 11% 基准 + 微调系数

详细功能与决策见 [`docs/`](./docs/)。

## 5 分钟跑起来

需要 Python 3.13+（推荐用 WorkBuddy 自带的隔离解释器，已装好 PySide6 6.11.2）。

```bash
# 1. 克隆
git clone https://github.com/Tearsvow233/-.git
cd babycat

# 2. 复制配置并填上你自己的 AI API Key
cp settings.example.json settings.json
# 编辑 settings.json，把 "ai_api_key" 改成你的智谱 glm-4-flash key
# （其他字段可以先保持默认）

# 3. 启动
python main.py
```

> 第一次启动会加载 500 张序列帧，约 7 秒。后续的冷启动优化见 docs。

## 打 release 包

```bash
# Windows，依赖 build.bat
build.bat
# 产物：dist/BabyCat.exe（约 178 MB，资源已内嵌）
```

## 目录结构

```
BabyCat/
├── main.py                 # 主程序（窗口/动画/状态机/提醒/设置面板/托盘）
├── word_push.py            # 每日单词推送
├── ai_chat.py              # AI 对话
├── reminder_parser.py      # 提醒文本解析
├── resources_rc.py         # 资源常量
├── BabyCat.spec            # PyInstaller 配置
├── build.bat               # 一键打包
├── settings.example.json   # 配置模板（不带 key）
├── assets/
│   ├── sprites/            # 500 张序列帧 PNG
│   ├── words/              # cet4_core.json 四级核心词库 2607 词
│   └── concept/            # 角色概念图
├── docs/                   # 需求与设计文档
│   ├── BabyCat项目交接包.md
│   ├── 宠物尺寸自适应需求.md
│   ├── 每日单词需求.md
│   └── AI提醒方案.md
├── tools/                  # 素材处理与测试脚本
└── BabyCat项目展示.docx     # 完整项目展示文档
```

## 路线图

- [x] 序列帧动作系统
- [x] 入睡状态机
- [x] AI 对话 + 三档提醒
- [x] 每日单词推送
- [x] 灵宠中心设置面板
- [x] 尺寸自适应（80–240px + 多屏 + DPI）
- [ ] 素材瘦身（500 帧 135 MB → ~63 MB）
- [ ] 图集化 sprite sheet + 预缩放缓存（目标冷启动 < 1s）
- [ ] 架构红线测试 + CI
- [ ] 动作权重调度 / 多角色
- [ ] proactive 主动行为（截图感知哈希）
- [ ] Agent Link 事件总线
- [ ] 拖拽物理手感

## 致谢

- 角色由 AI 生成
- 灵感与部分交互模式参考了 [dsh-pet 系列](./docs/BabyCat项目交接包.md) 开源项目

## License

仅供学习交流。