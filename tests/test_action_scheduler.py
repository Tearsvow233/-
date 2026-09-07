# -*- coding: utf-8 -*-
"""T7 动作权重调度的 pytest 包装。"""


def test_action_scheduler(run_tool):
    r = run_tool("test_action_scheduler.py", timeout=300)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
