# -*- coding: utf-8 -*-
"""T4 预缩放缓存验收的 pytest 包装（slow：真实素材，分钟级）。"""
import pytest


@pytest.mark.slow
def test_sprite_cache(run_tool):
    r = run_tool("test_sprite_cache.py", timeout=900)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
