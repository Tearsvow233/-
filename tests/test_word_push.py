# -*- coding: utf-8 -*-
"""单词推送（word_push）断言的 pytest 包装。"""


def test_word_push(run_tool):
    r = run_tool("test_word_push.py", timeout=300)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
