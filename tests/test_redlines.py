"""产品红线：Keel 不做反检测 —— **可机检**，不是一句口号。

跑法：
    .venv/Scripts/python.exe tests/test_redlines.py

── 为什么需要这个文件 ─────────────────────────────────────────

调研里有一个词必须点名：同类引擎 InkOS 有 `revise --mode anti-detect`
（专门的反检测改写）。**Keel 不做这个功能**，理由三条：

  1. 技术上必然失败 —— 检测已从词汇层转到叙事特征层。起点的维度里有
     「情感锚点偏移率」：测试者反馈「哪怕手写大纲、AI 扩写、再手动重写
     30% 关键段落，系统仍能标记超标」。**表层改写对付不了叙事层检测。**
  2. 伦理上不可辩护 —— 帮人把 AI 内容伪装成人类创作，是在对抗平台与
     读者的知情权，与 Keel 的合规定位直接冲突。
  3. 商业上自杀 —— 一旦被贴上「AI 洗稿工具」标签，平台的申诉通道、
     合作与生态全部关闭。

但「我们不做」这句话**没有任何机制背书**，明天有人加一个
`--mode anti-detect` 也不会有人拦。本文件就是那个机制。

正确的替代品是 `keel/audit/selfcheck.py`（如实报告）与
`keel/provenance/process.py`（创作过程留痕）——
**Keel 帮作者「真的写得更好」，不帮作者「看起来像人写的」。**

── 判据落在 AST 上，不落在文本搜索上 ─────────────────────────

第一版想当然地想禁词，立刻踩到两个假阳性：

  * `keel/pipeline/engines.py` 里有一个**内部函数就叫 `humanize`** ——
    它是把 JSON 里的值归一成字符串的**格式化工件**，跟反检测毫无关系。
  * `anti_slop.py` 里有一整套「**去 AI 味**」的说法（得分、修订、自动修）——
    那是**质量**指标，且属于作者既定的「只自动修文风类」边界，
    不是规避。

**一个会误报的守卫会被人删掉**，而删掉它比没有它更糟 ——
因为「我们有红线守卫」这句话就变成了假的。
所以判据是 AST：只查**标识符、CLI 标志、help 文案**，
注释与文档字符串里**允许**出现这些词（那里正是要写「我们为什么不做」的地方）。
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: 只禁**规避检测**这一族。故意**不**禁：
#:   * "去 AI 味" / anti_slop —— 那是质量指标，属于既定边界内的自动修文风
#:   * `humanize` —— engines.py 里的 JSON 归一化工件，与反检测无关
FORBIDDEN: tuple[str, ...] = (
    "anti_detect",
    "anti-detect",
    "antidetect",
    "anti_detection",
    "bypass_detect",
    "bypass",
    "降ai",
    "降 ai",
    "降_ai",
    "过检",
    "逃过检测",
    "规避检测",
    "洗稿",
    "ai 率",
)

#: 允许出现的标识符（含理由）。**每一项都必须写清楚为什么** ——
#: 一个没有理由的豁免就是后门。
ALLOWED_IDENTIFIERS: dict[str, str] = {
    "humanize": "engines.py 里把 JSON 值归一成字符串的格式化工件，与反检测无关",
}


class T:
    def __init__(self) -> None:
        self.passed = 0
        self.failed: list[str] = []

    def eq(self, got, want, label: str) -> None:
        if got == want:
            self.passed += 1
        else:
            self.failed.append(f"{label}\n      期望 {want!r}\n      实际 {got!r}")

    def ok(self, cond: bool, label: str) -> None:
        if cond:
            self.passed += 1
        else:
            self.failed.append(label)

    def group(self, name: str) -> None:
        print(f"\n  {name}")


def _py_files() -> list[Path]:
    return sorted((ROOT / "keel").rglob("*.py"))


def _hits(text: str) -> list[str]:
    low = text.lower()
    return [w for w in FORBIDDEN if w in low]


# ---------------------------------------------------------------------------
# 1. 标识符
# ---------------------------------------------------------------------------


def test_identifiers(t: T) -> None:
    t.group("1. 没有反检测的函数 / 类 / 常量")

    files = _py_files()
    t.ok(len(files) > 20, f"扫描到 {len(files)} 个源文件")

    offenders: list[str] = []
    for f in files:
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            offenders.append(f"{f.relative_to(ROOT)}: 语法错误 {exc}")
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
            elif isinstance(node, ast.Name):
                names.append(node.id)
            elif isinstance(node, ast.Attribute):
                names.append(node.attr)
            for n in names:
                if n.lower() in ALLOWED_IDENTIFIERS:
                    continue
                for bad in _hits(n):
                    offenders.append(
                        f"{f.relative_to(ROOT)}:{getattr(node, 'lineno', '?')} "
                        f"标识符 {n!r} 命中 {bad!r}"
                    )
    t.eq(offenders, [], "没有反检测标识符")


# ---------------------------------------------------------------------------
# 2. CLI：没有反检测开关
# ---------------------------------------------------------------------------


def test_cli_flags(t: T) -> None:
    t.group("2. CLI 没有反检测开关")

    src = (ROOT / "keel" / "cli.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    bad_flags: list[str] = []
    bad_help: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name not in {"add_argument", "add_parser"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                for bad in _hits(arg.value):
                    bad_flags.append(f"标志 {arg.value!r} 命中 {bad!r}")
        for kw in node.keywords:
            if kw.arg in {"help", "dest", "metavar"} and isinstance(kw.value, ast.Constant):
                for bad in _hits(str(kw.value.value)):
                    bad_help.append(f"{kw.arg}={kw.value.value!r} 命中 {bad!r}")
    t.eq(bad_flags, [], "没有反检测命令行标志")
    t.eq(bad_help, [], "没有反检测的帮助文案")

    # 正面确认：自检与过程报告两个**合规向**出口必须存在
    for cmd in ("submit-check", "process-report", "compliance"):
        t.ok(f'"{cmd}"' in src, f"存在合规出口 {cmd}")


# ---------------------------------------------------------------------------
# 3. 阈值公开，不藏
# ---------------------------------------------------------------------------


def test_thresholds_are_public(t: T) -> None:
    t.group("3. 阈值与词表公开在源码里（不藏）")

    # 一个靠**藏着阈值**才能工作的检测器，道德上站不住
    # （它诚实的用途是「告诉作者平台会怎么看」，那就必须让人看见），
    # 技术上也会在平台换口径的当天失效。
    # 故这里断言：词表是**明文**出现在源码里的，不是编码/加密后加载的。
    src = (ROOT / "keel" / "audit" / "rhythm.py").read_text(encoding="utf-8")
    for word in ("极其", "异常", "无比"):
        t.ok(word in src, f"副词词表在源码里明文可见（{word}）")

    import keel.audit.rhythm as R

    t.ok(
        all(isinstance(w, str) for ws in R._ADVERB_GROUPS.values() for w in ws),
        "副词词表是普通字符串（可读，不是字节串/编码串）",
    )
    for const in ("_ADVERB_PARAGRAPH_LIMIT", "_BARE_RUN_MIN", "_SCENE_DEVIATION_MAX"):
        t.ok(hasattr(R, const), f"阈值常量 {const} 是可导入的公开名字")


# ---------------------------------------------------------------------------
# 4. 红线写在文档里（且可变）
# ---------------------------------------------------------------------------


def test_documented(t: T) -> None:
    t.group("4. 红线写进了文档（且删掉会变红）")

    for name in ("README.md", "ENGINEERING_PLAN.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        t.ok("反检测" in text, f"{name} 里有红线条款")
        t.ok("红线" in text, f"{name} 里明确用了「红线」这个词")


# ---------------------------------------------------------------------------
# 5. 「去 AI 味」在边界内（不被本守卫误伤）
# ---------------------------------------------------------------------------


def test_quality_metrics_survive(t: T) -> None:
    """反向对照：质量向的能力**必须还在**。

    这条是防「守卫砍过头」：如果哪天有人为了让本文件更严格，
    把 anti_slop / CriticLoop 的自动修文风也一起禁掉，那才是真的坏 ——
    那是作者既定的产品边界（只自动修文风类，结构类留给人）。
    """
    t.group("5. 反向对照：质量向能力未被误伤")

    import keel.audit.anti_slop as A
    from keel.pipeline.engines import CriticLoop

    t.ok(hasattr(A, "scan_slop"), "anti_slop 仍在")
    t.ok(hasattr(CriticLoop, "run"), "CriticLoop 仍在（只自动修文风类）")

    from keel.audit.selfcheck import pre_submit_check
    from keel.provenance.process import build_process_report

    t.ok(callable(pre_submit_check), "合规自检仍在（红线的**正面对替代品**）")
    t.ok(callable(build_process_report), "创作过程报告仍在")


def main() -> int:
    print("═" * 64)
    print("  产品红线（不做反检测）—— 可机检守卫")
    print("═" * 64)
    t = T()
    try:
        test_identifiers(t)
        test_cli_flags(t)
        test_thresholds_are_public(t)
        test_documented(t)
        test_quality_metrics_survive(t)
    except ImportError as exc:
        print(f"\n  ✗ 模块尚不存在：{exc}")
        print("\n" + "─" * 64)
        print("  失败 1 · 通过 0")
        return 1

    print("\n" + "─" * 64)
    print(f"  通过 {t.passed} · 失败 {len(t.failed)}")
    if t.failed:
        print("  失败项：")
        for f in t.failed:
            print(f"    ✗ {f}")
        return 1
    print("  全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
