#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
T2 素材瘦身:批量将 assets/sprites 下的 PNG 重编码为 512 规范。

用法:
    python tools/resize_sprites_512.py            # 全量执行(先自检备份)
    python tools/resize_sprites_512.py --dry-run  # 只统计,不改文件
    python tools/resize_sprites_512.py --sample pace    # 只处理一个动作组,试质量用

规范(docs/宠物尺寸自适应需求.md §1):
    源图 512×512,覆盖 240px 显示 × 2 倍 DPI,留 6% 余量。
    - 原图 ≤512 的帧不缩小(只做 optimize 重存,可省体积)
    - LANCZOS 重采样,保留 RGBA 透明通道
    - PNG optimize + 提升压缩等级

安全:
    - 执行前校验 assets/sprites_512_backup_20260907 存在且帧数一致,否则拒绝执行
    - 逐帧写临时文件成功后原子替换,失败即停
"""
import io
import os
import sys
import glob
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPRITES = os.path.join(ROOT, "assets", "sprites")
BACKUP = os.path.join(ROOT, "assets", "sprites_512_backup_20260907")
TARGET = 512


def collect(prefix=None):
    files = sorted(glob.glob(os.path.join(SPRITES, "*.png")))
    if prefix:
        files = [f for f in files
                 if os.path.basename(f).rsplit("_", 1)[0].startswith(prefix)]
    return files


def check_backup(files):
    if not os.path.isdir(BACKUP):
        return False, "备份目录不存在: %s" % BACKUP
    n_backup = len(glob.glob(os.path.join(BACKUP, "*.png")))
    if n_backup != len(files):
        return False, "备份帧数(%d)与当前帧数(%d)不一致" % (n_backup, len(files))
    return True, ""


def main():
    dry = "--dry-run" in sys.argv
    prefix = None
    if "--sample" in sys.argv:
        i = sys.argv.index("--sample")
        prefix = sys.argv[i + 1]

    files = collect(prefix)
    print("待处理帧数: %d%s" % (len(files), ("  (动作组: %s)" % prefix) if prefix else ""))

    if not dry and prefix is None:
        ok, msg = check_backup(files)
        if not ok:
            print("ABORT:", msg)
            sys.exit(1)
        print("备份校验通过: %s" % BACKUP)

    before = after = 0
    resized = kept = 0
    for idx, path in enumerate(files, 1):
        before_size = os.path.getsize(path)
        with Image.open(path) as im:
            if im.mode not in ("RGBA", "LA", "P"):
                im = im.convert("RGBA")
            else:
                im.load()
            if max(im.size) > TARGET:
                im.thumbnail((TARGET, TARGET), Image.LANCZOS)
                resized += 1
            else:
                kept += 1
            if dry:
                buf = io.BytesIO()
                im.save(buf, "PNG", optimize=True, compress_level=9)
                after_size = len(buf.getvalue())
                buf.close()
            else:
                tmp = path + ".tmp.png"
                im.save(tmp, "PNG", optimize=True, compress_level=9)
                after_size = os.path.getsize(tmp)
                os.replace(tmp, path)
        before += before_size
        after += after_size
        if idx % 50 == 0 or idx == len(files):
            print("  [%3d/%d] 当前累计: %.1f MB -> %.1f MB"
                  % (idx, len(files), before / 1048576, after / 1048576))

    print("=" * 60)
    print("缩放帧: %d  保持帧: %d" % (resized, kept))
    print("体积: %.1f MB -> %.1f MB  (省 %.1f%%)"
          % (before / 1048576, after / 1048576,
             100 * (1 - after / before) if before else 0))
    if dry:
        print("DRY RUN: 未写入任何文件")


if __name__ == "__main__":
    main()
