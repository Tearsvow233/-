# -*- coding: utf-8 -*-
"""架构红线测试（交接包 T5）。

红线（参照原项目 tests/test_architecture.py 的做法，落地到本项目结构）：
1. `main.py` 行数预算：只许降不许涨（当前基线 2677 行，快照于 2026-09-07）
2. 纯逻辑层（ai_chat.py / reminder_parser.py）禁止 import 任何 Qt 绑定
   （AST 级检查，函数内/条件内 import 也抓得到）
3. 纯逻辑层禁止反向依赖 UI 层（main / word_push）——依赖只能 UI → 逻辑
4. main 私有面跨模块访问零命中：其他生产代码模块不得访问 `main._xxx`
5. 断言器自测：用临时伪造文件证明"禁 Qt / 私有面"检查器真的能抓违规，
   防止检查器写歪后恒过（静默失效比没有红线更危险）

纯逻辑层白名单（PURE_LOGIC_MODULES）是唯一允许零 Qt 的层；新增纯逻辑
模块时把文件名加进白名单即可自动纳入红线管辖。
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, ".")

ROOT = Path(__file__).resolve().parent.parent

PASS = []
FAIL = []

# ---------------------------------------------------------------------------
# 分层定义（唯一需要维护的配置）
# ---------------------------------------------------------------------------
MAIN_PY = ROOT / "main.py"
MAIN_PY_LINE_BUDGET = 2677  # 行数预算基线（2026-09-07 快照），只许降不许涨

# 纯逻辑层：禁 Qt、禁反向依赖 UI 层
PURE_LOGIC_MODULES = ["ai_chat.py", "reminder_parser.py", "action_scheduler.py"]

# UI 层：允许用 Qt；纯逻辑层禁止 import 它们
UI_MODULES = ["main.py", "word_push.py"]

# 生产代码 = UI 层 + 纯逻辑层（tools/ 下的测试与工具脚本不受红线管辖）
PRODUCTION_MODULES = UI_MODULES + PURE_LOGIC_MODULES

QT_PREFIXES = ("PySide6", "PyQt5", "PyQt6", "shiboken6", "shiboken2")


def check(name, ok, info=""):
    tag = "PASS" if ok else "FAIL"
    PASS.append(name) if ok else FAIL.append(name)
    print(f"[{tag}] {name} {info}")


# ---------------------------------------------------------------------------
# AST 检查器
# ---------------------------------------------------------------------------
def parse(path):
    src = Path(path).read_text(encoding="utf-8")
    return ast.parse(src, filename=str(path))


def imported_module_names(tree):
    """收集模块级+函数级所有 import 的顶层模块名（含 from X import Y 的 X）。"""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:  # 相对导入（level>0）无 module 名，跳过
                names.add(node.module.split(".")[0])
    return names


def find_qt_imports(tree):
    """返回文件中所有 Qt 绑定的 import 顶层名。"""
    return sorted(n for n in imported_module_names(tree) if n.startswith(QT_PREFIXES))


def find_cross_module_private_access(tree, target="main"):
    """返回 `target._xxx` 形式的跨模块私有属性访问（dunder 除外）的 (行号, 表达式)。"""
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                and node.value.id == target:
            if node.attr.startswith("_") and not node.attr.startswith("__"):
                hits.append((node.lineno, f"{target}.{node.attr}"))
    return hits


# ---------------------------------------------------------------------------
# 红线 1：main.py 行数预算
# ---------------------------------------------------------------------------
def test_main_line_budget():
    n = len(MAIN_PY.read_text(encoding="utf-8").splitlines())
    if n > MAIN_PY_LINE_BUDGET:
        check("红线1 main.py 行数预算", False,
              f"当前 {n} 行 > 预算 {MAIN_PY_LINE_BUDGET} 行（预算只许降不许涨；"
              f"请拆分逻辑到纯逻辑层模块，或先在测试中说明理由并收紧结构）")
    else:
        check("红线1 main.py 行数预算", True,
              f"当前 {n} / 预算 {MAIN_PY_LINE_BUDGET} 行"
              + ("（有余量，建议顺手把基线收紧到当前值）"
                 if n < MAIN_PY_LINE_BUDGET else ""))


# ---------------------------------------------------------------------------
# 红线 2/3：纯逻辑层禁 Qt、禁反向依赖 UI
# ---------------------------------------------------------------------------
def test_pure_logic_layer():
    for fname in PURE_LOGIC_MODULES:
        path = ROOT / fname
        if not path.exists():
            check(f"红线2 {fname} 纯逻辑模块存在", False, "文件缺失，白名单需要更新")
            continue
        check(f"红线2 {fname} 纯逻辑模块存在", True, "")
        tree = parse(path)

        qt = find_qt_imports(tree)
        check(f"红线2 {fname} 禁止 import Qt", not qt,
              f"发现 Qt import: {qt}（纯逻辑层要画界面请上抛给 UI 层）"
              if qt else "AST 级扫描零命中")

        banned = {Path(u).stem for u in UI_MODULES}
        rev = sorted(imported_module_names(tree) & banned)
        check(f"红线3 {fname} 禁止反向依赖 UI 层", not rev,
              f"发现 import: {rev}（依赖方向只能 UI → 纯逻辑）" if rev else "零命中")


# ---------------------------------------------------------------------------
# 红线 4：main 私有面跨模块访问零命中
# ---------------------------------------------------------------------------
def test_private_surface():
    for fname in PRODUCTION_MODULES:
        if fname == "main.py":
            continue
        path = ROOT / fname
        if not path.exists():
            continue
        hits = find_cross_module_private_access(parse(path), target="main")
        check(f"红线4 {fname} 不访问 main 私有成员", not hits,
              f"命中: {hits}（私有面是 main 的实现细节，请走公开接口）"
              if hits else "零命中")


# ---------------------------------------------------------------------------
# 红线 5：断言器自测（防恒过）
# ---------------------------------------------------------------------------
def test_sentinel_self_check():
    bad_qt = "import os\nif True:\n    from PySide6.QtCore import Qt\n"
    bad_priv = "import main\nx = main._cache_strips\n"
    good = "import json\nimport re\nfrom datetime import datetime\n"

    with tempfile.TemporaryDirectory() as td:
        f_bad_qt = Path(td) / "a.py"
        f_bad_priv = Path(td) / "b.py"
        f_good = Path(td) / "c.py"
        f_bad_qt.write_text(bad_qt, encoding="utf-8")
        f_bad_priv.write_text(bad_priv, encoding="utf-8")
        f_good.write_text(good, encoding="utf-8")

        caught_qt = find_qt_imports(parse(f_bad_qt)) == ["PySide6"]
        check("红线5 检查器能抓到函数内 Qt import", caught_qt,
              "" if caught_qt else "检查器漏检，AST 遍历有 bug！")

        caught_priv = find_cross_module_private_access(parse(f_bad_priv)) == \
            [(2, "main._cache_strips")]
        check("红线5 检查器能抓到 main._xxx 私有访问", caught_priv,
              "" if caught_priv else "检查器漏检，私有面扫描有 bug！")

        clean = not find_qt_imports(parse(f_good)) and \
            not find_cross_module_private_access(parse(f_good))
        check("红线5 干净文件不误报", clean,
              "" if clean else "检查器误报，正常代码被误伤！")


def main_():
    print("=" * 60)
    print("T5 架构红线测试")
    print("=" * 60)
    print(f"纯逻辑层: {PURE_LOGIC_MODULES}")
    print(f"UI 层:    {UI_MODULES}")
    print(f"main.py 行数预算: {MAIN_PY_LINE_BUDGET}（只许降不许涨）")
    print("-" * 60)

    test_main_line_budget()
    test_pure_logic_layer()
    test_private_surface()
    test_sentinel_self_check()

    print("-" * 60)
    print(f"结果: {len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项:")
        for name in FAIL:
            print(f"  - {name}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main_())
