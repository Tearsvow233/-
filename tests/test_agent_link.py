# -*- coding: utf-8 -*-
"""T9 Agent Link 事件总线 — pytest 包装。

沿用 T6 的模式：tests/ 里的 pytest 用例以子进程方式运行 tools/ 下的脚本并断言退出码，
避免同进程多 QApplication 冲突（这里 agent_link 不需要 QApplication，但保持一致风格）。
"""


def test_agent_link(run_tool):
    r = run_tool("test_agent_link.py", timeout=60)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
