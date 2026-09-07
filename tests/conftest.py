# -*- coding: utf-8 -*-
"""pytest 套件配置（交接包 T6）。

策略：tools/ 下已验收的断言脚本保留原样（独立可跑、带自检输出），
tests/ 里的 pytest 用例以子进程方式运行它们并断言退出码——
每个脚本都会创建 QApplication，子进程隔离避免同进程多 QApplication 冲突。

分类标记：
- slow        资产重型测试（图集 / 缓存，需真实素材，分钟级）
- network     需要外网的探索性脚本（默认不收集，见 pytest.ini）
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

# 必须在任何 Qt import 之前生效（虽然用例都是子进程，这里保个底）
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run_tool_script(name, timeout=900):
    """以当前解释器运行 tools/ 下的验收脚本，返回 CompletedProcess。"""
    script = TOOLS / name
    assert script.exists(), f"missing {script}"
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=timeout,
    )


import pytest  # noqa: E402


@pytest.fixture
def run_tool():
    return run_tool_script


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: 资产重型测试（图集/缓存，分钟级）")
    config.addinivalue_line("markers", "network: 需要外网的探索性脚本，CI 不跑")
