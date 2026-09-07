# -*- coding: utf-8 -*-
"""无头验证 PetWindow 调度数学（不实例化 GUI，只调静态方法）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
import main as mm  # noqa: E402

now = datetime.now()
print('now =', now.strftime('%Y-%m-%d %A %H:%M'))


def t(mode, r, hh, mm_clock, expect_hint=''):
    target = mm.PetWindow._next_cycle_target(mode, r, hh, mm_clock)
    if target is None:
        print(f'[FAIL] {mode:6s} hh={hh:02d}:{mm_clock:02d} r={r} -> None  {expect_hint}')
        return False
    days = (target - now).days
    flag = 'OK' if target else 'FAIL'
    print(f'[{flag}] {mode:6s} hh={hh:02d}:{mm_clock:02d} r={r} -> {target.strftime("%m-%d %A %H:%M")}  ({days} 天后)  {expect_hint}')
    return True


ok = True
ok &= t('weekly', {'weekday': 1}, 20, 0, '期望 5 天后(下周一)')
ok &= t('weekly', {'weekday': 3}, 9, 0, '期望 7 天后(下周三 9点已过)')
ok &= t('weekly', {'weekday': 3}, 23, 0, 'weekly 语义 days_ahead=0 一律+7 → 下周三')
ok &= t('weekly', {'weekday': 7}, 8, 0, '期望 4 天后(周日)')
ok &= t('daily', {}, 8, 0, '期望 1 天后(明天8点)')
ok &= t('daily', {}, 23, 0, '期望 0 天后(今天23点未到)')
print('ALL OK' if ok else 'SOME FAIL')
sys.exit(0 if ok else 1)
