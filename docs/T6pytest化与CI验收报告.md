# T6 pytest 化 + CI 验收报告

日期：2026-09-07 ｜ 结论：**通过**（本地 pytest 7/7 绿；CI 待推送 GitHub 后首跑）

## 1. 验收标准（来自交接包）

> `tools/` 脚本转为 pytest 用例；GitHub Actions 跑通。

## 2. pytest 化方案

**策略：子进程包装而非重写。** tools/ 下的验收脚本已各自带 13~48 项断言、自检输出和
正确的退出码，且都会创建 QApplication（同进程多 QApplication 会冲突）——因此 tests/
里的 pytest 用例以子进程运行原脚本并断言退出码 0，原脚本保留独立可跑能力，零重复代码。

### 新增文件

| 文件 | 说明 |
|---|---|
| `pytest.ini` | testpaths=tests，`--strict-markers`，标记 slow/network |
| `tests/conftest.py` | `run_tool` 夹具（offscreen + UTF-8 + 子进程） |
| `tests/test_architecture.py` | T5 架构红线（13 断言） |
| `tests/test_size_adapt.py` | T1 尺寸自适应（48 断言） |
| `tests/test_atlas.py` | T3 图集化（23 断言，slow） |
| `tests/test_sprite_cache.py` | T4 预缩放缓存（24 断言，slow） |
| `tests/test_schedule_math.py` | 提醒调度数学（纯逻辑） |
| `tests/test_chat_input_title.py` | 聊天输入框样式 |
| `tests/test_word_push.py` | 单词推送 |

### 未纳入 pytest 的脚本（有意为之）

- `test_ai_link.py` / `test_l3_e2e.py`：调外部 LLM API，无退出码断言，属探索脚本 → 预留 network 标记，CI 不跑
- `test_rembg.py`：需下载 u2net 模型 → 手动脚本
- `test_checkbox_image.py` / `test_dialog_style.py`：生成预览截图，无断言 → 手动脚本

## 3. 本地验证

```
$ python -m pytest -v
tests/test_architecture.py::test_architecture PASSED   [ 14%]
tests/test_atlas.py::test_atlas PASSED                 [ 28%]
tests/test_chat_input_title.py::test_chat_input_title PASSED [ 42%]
tests/test_schedule_math.py::test_schedule_math PASSED [ 57%]
tests/test_size_adapt.py::test_size_adapt PASSED       [ 71%]
tests/test_sprite_cache.py::test_sprite_cache PASSED   [ 85%]
tests/test_word_push.py::test_word_push PASSED         [100%]
============================== 7 passed in 32.55s ==============================
```

期间修过一个坑：conftest 里夹具 `run_tool` 与同名模块函数自引用，pytest 9 报
"Fixture called directly"——夹具改为返回 `run_tool_script` 后通过。

## 4. CI（GitHub Actions）

`.github/workflows/ci.yml`：

- **触发**：push / PR 到 main + 手动 workflow_dispatch
- **矩阵**：`ubuntu-latest` + `windows-latest`（双平台，fail-fast 关闭）
- **依赖**：setup-python 3.13 + pip 缓存；Linux 装 `libegl1 libgl1 libxkbcommon0
  libfontconfig1 libglib2.0-0`（PySide6 offscreen 必需）
- **安装**：`pip install -r requirements.txt`（新增声明式依赖）
- **执行**：`QT_QPA_PLATFORM=offscreen python -m pytest -v`
- **超时**：每 job 30 分钟

YAML 已用 PyYAML 解析校验（结构、步骤、矩阵均正确）。

跨平台可行性依据：main.py 的 win32 专属代码（GetLastInputInfo 空闲检测）已有
`sys.platform != "win32"` 守卫返回 0；settings.json 缺失时 `load_settings()` 回退
默认值——CI 全新 checkout 均安全。

## 5. git 仓库

项目原先不是 git 仓库，本次：

- `git init -b main`，`core.autocrlf=false`（避免二进制/混合内容换行污染）
- 新增 `.gitignore`：排除 build/ dist/ output/ snapshots/ cache/ logs/ .probe/
  .workbuddy/、137MB 素材备份、演示视频、settings.json（运行时生成）
- 入库约 739 文件 / 209MB（含 sprites 76MB + atlases 73MB，slow 测试必需）
- 两个提交：`6c6873a` 初始提交、`2720341` requirements.txt

**待用户完成**：在 GitHub 建仓后 `git remote add origin <url> && git push -u origin main`，
Actions 即自动首跑（本机无 gh CLI、GitHub 连接器未授权，无法代建远端）。

## 6. 结论

| 项 | 状态 |
|---|---|
| tools/ 脚本转 pytest 用例 | ✅ 7 个验收脚本全部纳入 |
| pytest 本地跑通 | ✅ 7 passed / 32.55s |
| GitHub Actions 就绪 | ✅ 工作流 + requirements + git 仓库（待 push 首跑） |

T1–T6 闭环。剩余 T7–T10（权重调度 / proactive / Agent Link / 拖拽物理）为低优先级。
