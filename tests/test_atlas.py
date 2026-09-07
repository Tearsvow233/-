# -*- coding: utf-8 -*-
"""T3 图集化验收的 pytest 包装（slow：真实素材，分钟级）。"""
import pytest


@pytest.mark.slow
def test_atlas(run_tool):
    r = run_tool("test_atlas.py", timeout=900)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
