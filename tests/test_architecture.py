# -*- coding: utf-8 -*-
"""架构红线（T5）的 pytest 包装。"""


def test_architecture(run_tool):
    r = run_tool("test_architecture.py", timeout=120)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
