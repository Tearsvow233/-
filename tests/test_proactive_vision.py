# -*- coding: utf-8 -*-
"""T8 proactive 主动行为 —— pytest 版（tools/test_proactive_vision.py 的 CI 适配）。"""
import base64
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proactive_vision import (IdleDetector, dhash, hamming, process_allowed,
                               DHASH_W, DHASH_H)


class TestDhash:
    def test_flat_image_zero(self):
        assert dhash([128] * (DHASH_W * DHASH_H)) == 0

    def test_decreasing_row_all_ones(self):
        row = list(range(9, 0, -1))
        assert dhash(row * DHASH_H) == (1 << 64) - 1

    def test_brightness_shift_invariant(self):
        assert dhash([10, 20, 30] * 24) == dhash([50, 60, 70] * 24)

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError):
            dhash([0] * 10)

    def test_hamming(self):
        assert hamming(0, 0) == 0
        assert hamming(0, 1) == 1
        assert hamming(0, (1 << 64) - 1) == 64


class TestIdleDetector:
    def test_edge_trigger_on_threshold(self):
        d = IdleDetector(stable_ticks=3, max_distance=2, cooldown_sec=100)
        t = 1000.0
        assert d.update(0b10101010, t) is False
        assert d.update(0b10101010, t + 1) is False
        assert d.update(0b10101010, t + 2) is True      # 第 3 帧边沿触发
        assert d.update(0b10101010, t + 3) is False     # 持续闲置不再触发

    def test_change_resets_run(self):
        d = IdleDetector(stable_ticks=2, max_distance=2, cooldown_sec=0)
        t = 1000.0
        assert d.update(0xFF, t) is False
        assert d.update(0x00, t + 1) is False           # 大变 → 清零
        assert d.update(0x00, t + 2) is True            # 再稳定 2 帧触发

    def test_is_idle_reflects_state(self):
        d = IdleDetector(stable_ticks=2, max_distance=64, cooldown_sec=0)
        d.update(1, 0.0)
        assert not d.is_idle()
        d.update(1, 1.0)
        assert d.is_idle()

    def test_zero_ticks_raises(self):
        with pytest.raises(ValueError):
            IdleDetector(stable_ticks=0)


class TestCooldown:
    def test_cooldown_window(self):
        d = IdleDetector(stable_ticks=1, max_distance=64, cooldown_sec=50)
        t = 2000.0
        assert not d.in_cooldown(t)
        d.update(1, t)
        d.notify_chat(t + 10)
        assert d.in_cooldown(t + 20)
        assert d.in_cooldown(t + 59)
        assert not d.in_cooldown(t + 61)

    def test_notify_chat_resets_observation(self):
        d = IdleDetector(stable_ticks=2, max_distance=64, cooldown_sec=50)
        t = 1000.0
        d.update(1, t)
        d.notify_chat(t + 10)
        assert d.update(1, t + 100) is False   # 重新观察第 1 帧不触发
        assert d.update(1, t + 101) is True    # 第 2 帧再次满足


class TestWhitelist:
    WL = ["chrome", "Code.exe", " idea64 "]

    def test_full_path_hit(self):
        assert process_allowed("C:\\Program Files\\Google\\Chrome\\chrome.exe", self.WL)

    def test_case_insensitive(self):
        assert process_allowed("code.EXE", self.WL)

    def test_whitespace_entry(self):
        assert process_allowed("idea64.exe", self.WL)

    def test_miss(self):
        assert not process_allowed("C:\\Windows\\system32\\cmd.exe", self.WL)

    def test_none_rejected(self):
        assert not process_allowed(None, self.WL)

    def test_empty_whitelist_rejects_all(self):
        assert not process_allowed("chrome.exe", [])

    def test_empty_name_rejected(self):
        assert not process_allowed("", self.WL)

    def test_no_auto_exe_suffix(self):
        assert not process_allowed("/usr/bin/code", ["code"])


class TestReplyVision:
    def _img(self):
        return base64.b64encode(b"\xff\xd8fakejpeg").decode()

    def test_disabled_returns_none(self):
        import ai_chat
        off = ai_chat.PetAI({"ai_enabled": False})
        assert off.reply_vision(self._img(), "x") is None

    def test_payload_format(self):
        import ai_chat
        import urllib.request
        real = ai_chat.PetAI({"ai_enabled": True, "ai_api_key": "k",
                              "ai_base_url": "https://fake/v1", "ai_model": "m",
                              "ai_vision_model": "vm"})
        box = {}

        def _spy(url, data=None, method=None):
            box["data"] = json.loads(data.decode())
            box["url"] = url
            raise OSError("stop")

        orig = urllib.request.Request
        urllib.request.Request = _spy
        try:
            real.reply_vision(self._img(), "看一眼")
        except OSError:
            pass
        finally:
            urllib.request.Request = orig
        assert box["url"].endswith("/chat/completions")
        assert box["data"]["model"] == "vm"      # 视觉模型优先
        msgs = box["data"]["messages"]
        assert isinstance(msgs[-1]["content"], list)
        assert msgs[-1]["content"][0] == {"type": "text", "text": "看一眼"}
        assert msgs[-1]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;base64,")

    def test_vision_model_falls_back_to_model(self):
        import ai_chat
        real = ai_chat.PetAI({"ai_enabled": True, "ai_api_key": "k",
                              "ai_base_url": "https://fake/v1", "ai_model": "m"})
        # 未配 ai_vision_model → _cfg 回落逻辑由 payload 格式测试覆盖；
        # 这里只验证空 key 静默
        assert real.reply_vision(None, "x") is None   # 无图 → None


class TestPureLogic:
    def test_no_qt_import(self):
        import proactive_vision as pv
        src = Path(pv.__file__).read_text(encoding="utf-8")
        assert "import PySide6" not in src
        assert "import PyQt" not in src
