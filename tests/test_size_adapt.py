# -*- coding: utf-8 -*-
"""T1 尺寸自适应验收的 pytest 包装。"""


def test_size_adapt(run_tool):
    r = run_tool("test_size_adapt.py", timeout=600)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
