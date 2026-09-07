# -*- coding: utf-8 -*-
"""提醒解析调度数学（纯逻辑）的 pytest 包装。"""


def test_schedule_math(run_tool):
    r = run_tool("test_schedule_math.py", timeout=120)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
