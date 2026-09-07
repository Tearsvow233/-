# -*- coding: utf-8 -*-
"""聊天输入框标题样式断言的 pytest 包装。"""


def test_chat_input_title(run_tool):
    r = run_tool("test_chat_input_title.py", timeout=300)
    assert r.returncode == 0, f"\n{r.stdout}\n{r.stderr}"
