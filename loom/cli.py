"""Loom 命令行入口。

    python -m loom.cli write    "一句话想法" --out out/       想法 -> IR -> 正文
    python -m loom.cli web      [--port 8000]              启动本地网页界面（浏览器里操作）
    python -m loom.cli audit    <ir.json>     跑故事体检
    python -m loom.cli proposals <ir.json>    列出结构提案（待裁决）
    python -m loom.cli decide   <ir.json> --all --accept   一键采纳（唯一的生效入口）
    python -m loom.cli audience <ir.json>     观众模拟（留存曲线 + 原话）
    python -m loom.cli render   <ir.json> -f text|fountain|storyboard|ink|renpy
    python -m loom.cli outline  <ir.json>     输出大纲
    python -m loom.cli lore     <ir.json> --text "沈砚掏出腰牌"
    python -m loom.cli play     <ir.json> --runs 500
    python -m loom.cli compliance <ir.json>
    python -m loom.cli submit-check <ir.json>    投稿前合规自检（能不能投）
    python -m loom.cli process-report <ir.json> --out 过程.md   创作过程报告（申诉举证）
    python -m loom.cli templates
    python -m loom.cli api handshake           插件契约：稳定 JSON（薄客户端用）
"""

from __future__ import annotations

import argparse
import webbrowser
import json
import sys
import inspect
from pathlib import Path

from . import __version__
from . import api as loom_api
from .clock import wall_iso
from .audience import AudienceSimulator
from .audience.cognitive import scan_ir as scan_cognitive_ir
from .audit.anti_slop import scan_ir as scan_slop_ir
from .audit.craft import scan_ir as scan_craft_ir
from .audit.dress import scan_ir as scan_dress_ir
from .audit.selfcheck import pre_submit_check
from .audit.transportation import scan_ir as scan_transport_ir
from .ir.enums import ArcShape, Medium
from .ir.loading import IRLoadError, load_ir
from .ir.models import NarrativeIR
from .ir.templates import list_templates
from .llm import ModelCallError, TokenLedger, build_generator
from .llm.workbuddy_provider import (
    PendingGeneration,
    WorkBuddyAnswerError,
    queue_dir_for,
)
from .pipeline import LoomPipeline
from .policy import OverriddenProse, PolicyError, blocked_reason
from .provenance.awareness import awareness_line
from .provenance.meter import ProvenanceLedger
from .provenance.process import build_process_report
from .render import (
    render_fountain,
    render_html,
    render_ink,
    render_renpy,
    render_storyboard,
    render_text,
)
from .render.text import render_outline
from .render.glance import render_glance
from .render.hub import render_hub
from .web import serve as serve_web
from .runtime.director import StoryRuntime, randomized_playthroughs
from .validators import run_all, available, registry_stats, get_validator
from .validators import REQUIRES, REPORTS


def _load(path: str) -> NarrativeIR:
    """读一份 IR，把 `IRLoadError` 翻译成**说人话的** SystemExit。

    读取本身只有一份实现（`loom/ir/loading.py`）；这里只负责**面向人**的表达。
    面向插件的表达在 `loom/api.py`（结构化错误），两者故意不同：

    为什么不让它直接抛 `FileNotFoundError`：那条 traceback 对作者
    一点用都没有 —— 它说的是「Python 打不开文件」，而作者需要知道的
    是「那份 IR 不在这儿，先跑 loom write 生成一个」。
    **把 traceback 甩给用户，是把调试成本转嫁给不懂调试的人。**
    """
    try:
        return load_ir(path)
    except IRLoadError as exc:
        if exc.kind == IRLoadError.MISSING:
            raise SystemExit(
                f"\n  找不到 IR 文件：{exc.path}\n"
                f"  可能的原因：路径写错了，或还没有生成过。\n"
                f"  先生成一个：loom write \"一句话想法\" --out out/\n"
                f"  再来看它：  loom audit out/<目录>/ir.json\n"
            ) from exc
        # 坏 IR 也要说人话（JSON 截断 / 版本不对 / 字段非法）
        raise SystemExit(
            f"\n  读不出这份 IR：{exc.path}\n  原因：{exc.reason}\n"
            f"  若是旧版本生成的，用 loom write 重跑一份即可。\n"
        ) from exc


def _slug(title: str, *, limit: int = 40) -> str:
    """标题 -> 安全的目录名。

    刻意**不加时间戳**：同一个想法重跑应当**覆盖**同一份报告，
    而不是在磁盘上堆一串只差几秒的副本。确定性目录名还带来一个好处 ——
    「我刚才那份报告在哪」这个问题永远有同一个答案。
    """
    # 注意：Python 里 `'中'.isalnum()` 是 **True**，所以中文标题会原样保留，
    # 不会被清成空 —— 这正是我们想要的（中文用户是主要场景）。
    # 兜底只针对标题为空或全是标点的极端情况。
    safe = "".join(
        ch if (ch.isalnum() or ch in "-_") else "-" for ch in (title or "").strip()
    ).strip("-")
    return (safe or "untitled")[:limit]


#: 媒介 → 该媒介的**主产物**（渲染器, 文件名, 枢纽里的中文标签）。
#: 依据 P2（可达性是乘数）：用户选了「影视剧本」，就该在**同一个命令**里
#: 直接拿到 `script.fountain`。此前 `write --medium screenplay` 只写 novel.md，
#: 要拿剧本还得再学一条 `render -f fountain -o ...` —— 第一分钟路径是断的，
#: 用户看到的现象就是「它不会自动完成剧本创作」。
#: novel / web_novel 不在此表：它们的主产物就是正文 novel.md（已有逻辑处理，
#: 且 web_novel 受 policy 闸门约束）。
_MEDIUM_ARTIFACT: dict[str, tuple] = {
    "screenplay": (render_fountain, "script.fountain", "Fountain 剧本"),
    "micro_drama": (render_fountain, "script.fountain", "Fountain 剧本（微短剧）"),
    "interactive_fiction": (render_ink, "story.ink", "Ink 互动小说"),
    "visual_novel": (render_renpy, "script.rpy", "Ren'Py 脚本"),
    "comic": (render_storyboard, "storyboard.json", "漫画分镜 JSON"),
}


def write_story(
    *,
    idea: str,
    out: str | None = None,
    out_root: str | None = None,
    model: str | None = None,
    medium: str = "novel",
    arc: str = "man_in_a_hole",
    template: str = "save_the_cat",
    scenes: int = 5,
    words: int = 800,
    force_prose: bool = False,
    rounds: int = 2,
    on_step=None,
) -> dict:
    """想法 -> IR -> 正文，并写出全部产物（含 loom.html 枢纽）。

    **这是 CLI `write` 与本地网页服务共用的唯一生成入口** ——
    UI 只是视图，产品本体是 IR；网页与命令行必须走同一份逻辑，否则会漂移
    （铁律：任何「直接生成文本」的捷径都是架构倒退）。

    返回 dict，含：outdir / ir / report / artifacts / prose_note /
    hub_path / summary / report_text / generator_id / offline。
    """
    ledger = TokenLedger()
    # workbuddy 驱动的队列目录**从想法派生**，不放在 outdir 里 ——
    # outdir 要等流水线跑完才有（标题由前提层产出），而队列在第一行就得就绪。
    # 按想法哈希分目录：换想法就是换队列，不会误用上一个故事的 prose#1。
    queue_dir = None
    if model == "workbuddy":
        base = Path(out) if out else (Path(out_root) if out_root else Path("out"))
        queue_dir = str(queue_dir_for(idea, base))
    gen = build_generator(
        model=model, ledger=ledger, offline=not model, queue_dir=queue_dir
    )
    pipe = LoomPipeline(
        gen, ledger=ledger, on_step=on_step or (lambda m: None)
    )
    res = pipe.run(
        idea,
        medium=Medium(medium),
        arc_shape=ArcShape(arc),
        template_id=template,
        scene_count=scenes,
        words_per_scene=words,
        max_rounds=rounds,
    )

    # 输出目录**有默认值** —— 原实现不传 `--out` 就一个文件都不写，
    # 于是 report.html 根本不会出现，第一分钟路径是断的。
    # 默认目录名从标题派生（**不用时间戳**）：同一个想法重跑会覆盖同一份报告，
    # 这是有意的 —— 重跑应当更新报告，而不是在磁盘上堆一串副本。
    # `out` 是**精确目录**（CLI `--out`，享确切路径语义）；
    # `out_root` 是**根目录**，最终目录为 `<out_root>/<标题 slug>/`
    # （网页服务用它把每次生成隔离到自己的子目录，互不覆盖）。
    if out:
        outdir = Path(out)
    else:
        root = Path(out_root) if out_root else Path("out")
        outdir = root / _slug(res.ir.title)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "ir.json").write_text(res.ir.to_json(), encoding="utf-8")
    (outdir / "outline.md").write_text(render_outline(res.ir), encoding="utf-8")
    # 正文：网文媒介默认**不出**（平台禁 AI 直出正文，见 loom/policy.py）。
    # 用 try 而不是预先 if —— 判定逻辑只应存在一处（policy 模块），
    # CLI 不该复制一份媒介名单，否则两边会漂。
    try:
        (outdir / "novel.md").write_text(
            render_text(res.ir, force_prose=force_prose), encoding="utf-8"
        )
        prose_note = "novel.md"
    except PolicyError as exc:
        prose_note = "~~novel.md~~（未生成，见下方说明）"
        print(f"\n  ⚠ 未生成正文：{exc}")
        print("    需要正文时加 `--force-prose`（风险自负，见 loom/policy.py）。")
    (outdir / "audience.json").write_text(
        json.dumps(
            AudienceSimulator(gen).run(res.ir).to_dict(),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    # HTML 报告：**可达性交付物**。
    # 其余产物都是给机器或给命令行读者的；这一份是能双击打开、能发给别人的。
    # 依据 F7（门槛决定采用）与 F5（M0–M3 获客靠分享）。
    report_path = outdir / "report.html"
    (report_path).write_text(render_html(res.ir, res.report), encoding="utf-8")
    # 第一分钟速览：默认产出，新用户无需学第二条命令即拿到一屏可分享卡
    # （glance 与媒介无关 —— 它只渲染大纲 / 人物卡 / 体检头三行）
    glance_path = outdir / "glance.html"
    glance_path.write_text(render_glance(res.ir, res.report), encoding="utf-8")
    # C2PA 内容凭证：合规从「中国」变「全球」，主路径默认导出（纯数据、未签名）。
    # 与媒介无关 —— AI 参与度溯源对任何媒介都该被证明，不只是剧本。
    ledger = ProvenanceLedger()
    if res.ir.provenance:
        ledger.records = list(res.ir.provenance)
        ledger.attach(res.ir)
    c2pa_path = outdir / "c2pa.json"
    c2pa_path.write_text(ledger.to_c2pa_json(res.ir), encoding="utf-8")
    # 一屏枢纽：把上面所有产物汇成一张可导航的屏（主页）。
    # 零依赖（纯 stdlib 生成 HTML + 内联 SVG/JS），守铁律 6。
    # 不再把 14 个子命令摊给用户 —— 首屏只亮要点，命令面板可达全部动作。
    # 媒介主产物：选了什么媒介，就把那个媒介的成品文件直接写出来。
    # 失败要**吭声**再继续 —— 一个媒介渲染器挂掉不该让整次生成失败，
    # 但静默吞掉会让「我明明选了剧本却没剧本」变成无法定位的问题。
    medium_key = getattr(res.ir.medium, "value", str(res.ir.medium))
    art = _MEDIUM_ARTIFACT.get(medium_key)
    if art:
        render_fn, fname, label = art
        try:
            (outdir / fname).write_text(render_fn(res.ir), encoding="utf-8")
            artifacts_medium = (fname, label)
        except Exception as exc:  # 渲染器挂了：留痕，但不拖垮整条流水线
            artifacts_medium = None
            print(f"\n  ⚠ 未能生成 {fname}：{type(exc).__name__}: {exc}")
    else:
        artifacts_medium = None

    artifacts = [
        ("ir.json", "叙事 IR（产品本体）"),
        ("report.html", "深度结构体检报告"),
        ("glance.html", "一屏可分享速览卡"),
        ("c2pa.json", "C2PA 内容凭证"),
        ("audience.json", "观众模拟结果"),
        ("outline.md", "纯大纲"),
    ]
    if force_prose or prose_note == "novel.md":
        artifacts.insert(1, ("novel.md", "生成的正文"))
    if artifacts_medium:
        artifacts.insert(1, artifacts_medium)  # 媒介主产物排最前：它就是这次要的东西
    hub_path = outdir / "loom.html"
    hub_path.write_text(
        render_hub(res.ir, res.report, artifacts=artifacts), encoding="utf-8"
    )
    return {
        "outdir": outdir,
        "ir": res.ir,
        "report": res.report,
        "artifacts": artifacts,
        "prose_note": prose_note,
        "medium_artifact": artifacts_medium[0] if artifacts_medium else None,
        "hub_path": hub_path,
        "summary": res.summary(),
        "report_text": res.report.render(f"{res.ir.title} · 结构体检"),
        "generator_id": gen.model_id,
        "offline": not model,
    }


def _resolve_model(args: argparse.Namespace) -> str | None:
    """`--generator` 是 `--model` 的可读别名，两者不该各自演化。

    `workbuddy` 不是模型名，是一种**驱动方式**（不发请求，发问题），
    把它塞进 `--model` 只是为了不改流水线；对外应当有一个说人话的开关。
    """
    g = getattr(args, "generator", None)
    if g == "workbuddy":
        return "workbuddy"
    if g == "mock":
        return None
    return args.model


def cmd_write(args: argparse.Namespace) -> int:
    """想法 -> IR -> 正文。1.0 阶段的主命令。"""
    try:
        return _cmd_write(args)
    except PendingGeneration as exc:
        # 不是失败，是**在等人**。退出码要跟「出错」区分开，
        # 否则脚本无法判断该重试还是该报错。
        print(f"\n  ⏸  {exc}")
        print("\n  这是 workbuddy 驱动：Loom 不发请求，它发问题 ——")
        print("  提示词已经写成待填文件，等你（或 WorkBuddy / 任意 LLM 界面）填 output。")
        print("  填好后**重跑同一条命令**：已填的不会丢，流水线接着往下走。")
        return 3
    except WorkBuddyAnswerError as exc:
        print(f"\n  ✗ 答案格式不对：{exc}")
        return 4
    except ModelCallError as exc:
        # 没设 key / 连不上 / 限流 —— 这些用户能自己修，别甩 traceback。
        print(f"\n  ✗ {exc}")
        return 2


def cmd_run(args: argparse.Namespace) -> int:
    """自动驾驶：不喊停就一直写，直到 **IR 派生的停止判据**成立。

    与 `write` 是两种契约：`write` 一次跑完、逐个确认；`run` 无人值守、
    靠停止判据收尾。所以它们是两条命令，不是一个参数。

    「我不喊停」不是停止条件，是侥幸 —— 停止判据全部从 IR 派生：
    达标场数 / 承诺兑现 / 结局锚点兑现 / 预算闸；结构破损与漂移则**暂停**等人。
    """
    from .pipeline.auto import AutoConfig, AutoWriter
    from .pipeline.budget import Budget
    from .pipeline.preflight import PreflightError

    idea = args.idea
    model = _resolve_model(args)
    base = Path(args.out) if args.out else Path("out")
    queue_dir = str(queue_dir_for(idea, base)) if model == "workbuddy" else None
    ledger = TokenLedger()
    gen = build_generator(
        model=model, ledger=ledger, offline=not model, queue_dir=queue_dir
    )

    cfg = AutoConfig(
        target_scenes=args.scenes,
        words_per_scene=args.words,
        budget=Budget(
            max_scenes=args.max_scenes,
            max_cost=args.max_cost,
            max_minutes=args.max_minutes,
        ),
    )
    ckpt = base / ".auto" if args.checkpoint else None
    writer = AutoWriter(
        gen, ledger=ledger, cfg=cfg, on_step=lambda m: print(f"  · {m}")
    )

    print(f"\n  自动驾驶启动：《{idea[:30]}》")
    print(
        f"  目标 {args.scenes} 场 · 预算闸："
        f"场数≤{args.max_scenes} · 成本≤{args.max_cost} · 分钟≤{args.max_minutes}\n"
    )

    try:
        res = writer.run(
            idea,
            medium=Medium(args.medium),
            arc_shape=ArcShape(args.arc),
            template_id=args.template,
            checkpoint_dir=ckpt,
            resume_ir=Path(args.resume_from) if args.resume_from else None,
        )
    except PreflightError as exc:
        # 计划不合格不许上路：自主性会放大计划的质量，坏计划 × 自动驾驶
        # = 很长很长的烂故事。这里停下来是**保护**，不是阻碍。
        print(f"\n  ✗ {exc}")
        return 5
    except PendingGeneration as exc:
        print(f"\n  ⏸  {exc}")
        print("\n  workbuddy 驱动：提示词已写成待填文件，填好后重跑同一条命令。")
        return 3
    except WorkBuddyAnswerError as exc:
        print(f"\n  ✗ 答案格式不对：{exc}")
        return 4
    except ModelCallError as exc:
        print(f"\n  ✗ {exc}")
        return 2

    outdir = base / _slug(res.ir.title)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "ir.json").write_text(res.ir.to_json(), encoding="utf-8")
    (outdir / "report.html").write_text(
        render_html(res.ir, res.report), encoding="utf-8"
    )
    (outdir / "glance.html").write_text(
        render_glance(res.ir, res.report), encoding="utf-8"
    )
    # 决策留痕：合规资产。台账记「AI 参与了哪一场」= 免责证据；
    # 这里记「每一场为什么这么写」= 主张证据（申诉时真正需要的东西）。
    (outdir / "decisions.json").write_text(
        json.dumps(res.decisions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + res.report.render(title="收尾体检"))
    print(f"\n  停止原因：{res.stop_reason}"
          f"{'（已暂停，等你裁决）' if res.paused else ''}")
    print(f"  场景 {len(res.ir.scenes)} 场 · 正文 {res.ir.word_count()} 字")
    print(f"  结构决策 {len(res.decisions)} 条（已留痕为提案，共 "
          f"{len(res.ir.proposals)} 条）")

    # 留痕只是**登记了提案**，它还不是证据 —— 没被裁决的提案等于没发生。
    # 所以这里必须把人接回循环：告诉作者下一步该敲什么，以及为什么必须敲。
    pending = res.ir.pending_proposals()
    if pending:
        print(f"\n  ⚠ {len(pending)} 条提案待你裁决 —— **待裁决不构成证据**。")
        print("    机器提了案，但「人做过判断」这件事只有你裁了才存在：")
        print(f"      loom proposals {outdir / 'ir.json'}")
        print(f"      loom decide {outdir / 'ir.json'} --all --accept"
              "   # 或去掉 --accept 表示驳回")
        print("    驳回的证据力强于采纳（见 loom process-report）。")
        if res.paused and args.checkpoint:
            # 续跑必须**显式**指回人裁过的那份 IR。不写明这一句，
            # 作者会下意识地再跑一次同一条命令 —— 而那会用检查点里
            # 那份**没人裁过**的 IR 覆盖他刚做的判断，且一声不响。
            paused_ir = ckpt / "paused.json"
            print(f"\n  续跑（带上你的裁决）：")
            print(f"      loom run \"{idea}\" --checkpoint --resume-from {paused_ir}")
            print("    不指定 --resume-from 会从检查点续跑 = **这次裁决作废**。")

    print(f"\n  产物：{outdir}/")
    for name in ("ir.json", "report.html", "glance.html", "decisions.json"):
        print(f"    · {name}")
    return 0


def _cmd_write(args: argparse.Namespace) -> int:
    result = write_story(
        idea=args.idea,
        out=args.out,
        model=_resolve_model(args),
        medium=args.medium,
        arc=args.arc,
        template=args.template,
        scenes=args.scenes,
        words=args.words,
        force_prose=args.force_prose,
        rounds=args.rounds,
        on_step=lambda m: print(f"  · {m}"),
    )
    print(f"生成器：{result['generator_id']}"
          f"{'（离线确定性参考实现）' if result['offline'] else ''}\n")
    print(result["report_text"])
    print()
    print(result["summary"])
    files = (f"ir.json · {result['prose_note']} · "
             f"outline.md · audience.json · report.html · glance.html · "
             f"c2pa.json · loom.html")
    if result.get("medium_artifact"):
        # 媒介主产物排在最前 —— 它就是这次用户真正要的那个文件。
        files = f"{result['medium_artifact']} · " + files
    print(f"\n已写入 {result['outdir']}/：{files}")

    # 自动打开：把「知道有个文件」变成「已经看见了」。
    # 依据 F7 —— 门槛决定采用，每少一步操作就多一个人真正用上。
    # 现在打开的是一屏枢纽（主页），而不是散落报告之一。
    if getattr(args, "no_open", False):
        print(f"\n  枢纽：{result['hub_path']}（已按 --no-open 跳过自动打开）")
    else:
        print(f"\n  枢纽：{result['hub_path']}")
        try:
            opened = webbrowser.open(result["hub_path"].resolve().as_uri())
        except Exception:  # 无图形环境 / 无默认浏览器时不能让命令失败
            opened = False
        print("  🌐 已用默认浏览器打开。" if opened else "  （未能自动打开，请手动双击上面的路径。）")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    """启动本地网页界面（零依赖），让非技术用户也能在浏览器里操作 Loom。

    CLI 仍是 power-user 路径；网页只是把同一份 `write_story` 包成表单。
    服务只监听 127.0.0.1，数据不出本机。

    每次生成写到 `<base_out>/<标题 slug>/`，互不覆盖；`--out` 指定根目录。
    """
    base_out = Path(args.out) if args.out else Path("out")

    def writer(**kw):
        kw.pop("out", None)  # 网页路径不走精确目录，改走 out_root（按 slug 隔离）
        kw["out_root"] = str(base_out)
        return write_story(**kw)

    serve_web(
        writer,
        host=args.host,
        port=args.port,
        base_out=base_out,
    )
    return 0


def cmd_audience(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    gen = build_generator(model=args.model, offline=not args.model)
    sim = AudienceSimulator(gen)
    rep = sim.run(
        ir,
        personas=args.personas.split(",") if args.personas else None,
        qualitative=not args.no_llm,
    )
    print(rep.render())
    if args.json:
        Path(args.json).write_text(
            json.dumps(rep.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n已写入 {args.json}")
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    report = run_all(ir)
    # 文本工艺：**只通报，不进健康分**（见 Report.advisory 的说明）。
    # 「结构健康分」不该被工艺/文风信号推动 —— 否则加几个检测器，
    # 分数就降，读者分不清是「结构变差了」还是「多装了检查」。
    report.add_advisory(*scan_slop_ir(ir))  # 句子层面：AI 味
    report.add_advisory(*scan_craft_ir(ir))  # 段落层面：张力/控制感/现实效应/展示不告知
    report.add_advisory(*scan_dress_ir(ir))  # 跨章：风格漂移（DRESS 三维）
    report.add_advisory(*scan_transport_ir(ir))  # 传输度六维
    report.add_advisory(*scan_cognitive_ir(ir))  # 认知负荷窗口累加
    print(report.render(f"{ir.title} · 故事体检报告"))
    return 0 if report.passed() else 1


def cmd_recheck(args: argparse.Namespace) -> int:
    """用**当前的**校验器重跑一份**旧的** IR，并报出「上次以来变了什么」。

    ── 为什么不是 `audit` ─────────────────────────────────────────
    `audit <ir.json>` 在功能上已经能重跑旧 IR。缺的是**对比**：
    用户回到一份旧稿子，他真正想知道的不是「现在多少分」，
    而是「**和上次比，多了什么**」。

    这个对比就是 a16z 说的**微笑曲线**的触发机制：
    留存要重定基到 M3，而「能力变强后老用户回来」是少数几个
    能让曲线重新上翘的东西。Loom 发布新校验器时，老用户的旧 IR
    会自动获得新的体检结果 —— **但用户必须看得见，钩子才存在。**

    ── 快照存哪 ───────────────────────────────────────────────────
    默认写在 IR 同目录的 `<ir 名>.audit.json`（可用 `--snapshot` 改）。
    **刻意不存进 IR 内部** —— IR 是 `extra="forbid"` 的硬契约，
    往里塞一份体检快照会污染产品本体（铁律 4）。
    """
    ir = _load(args.ir)
    report = run_all(ir)
    now = {
        f.code: (f.severity.value, f.scene_id or "", f.message)
        for f in report.findings
    }

    snap_path = Path(args.snapshot) if args.snapshot else Path(
        str(args.ir).rsplit(".", 1)[0] + ".audit.json"
    )

    print(report.render(f"{ir.title} · 重新体检"))

    if snap_path.exists():
        try:
            old = json.loads(snap_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"\n  ⚠ 快照读不出来（{exc}），跳过对比。")
            old = None
        if isinstance(old, dict):
            new_codes = sorted(set(now) - set(old))
            gone_codes = sorted(set(old) - set(now))
            changed = sorted(
                c for c in set(now) & set(old)
                if old[c][0] != now[c][0]
            )
            print(f"\n── 与上次体检的差异（快照 {snap_path.name}）──")
            print(f"  新增 {len(new_codes)} · 已解决 {len(gone_codes)} · "
                  f"严重度变化 {len(changed)}")
            if new_codes:
                print("\n  【新增】")
                for c in new_codes:
                    print(f"    + {c}（{now[c][0]}）{now[c][2][:60]}")
            if gone_codes:
                print("\n  【已解决】")
                for c in gone_codes:
                    print(f"    - {c}")
            if changed:
                print("\n  【严重度变化】")
                for c in changed:
                    print(f"    ~ {c}: {old[c][0]} → {now[c][0]}")
            if not (new_codes or gone_codes or changed):
                print("  与上次完全一致。")
    else:
        print(f"\n  （无历史快照 {snap_path.name}；本次结果已存为下次的基线。）")

    snap_path.write_text(
        json.dumps(now, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  快照已写入 {snap_path}")
    return 0


def cmd_render(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    renderers = {
        "text": lambda: render_text(ir, show_meta=args.meta, chronological=args.chrono,
                                force_prose=args.force_prose),
        "fountain": lambda: render_fountain(ir),
        "storyboard": lambda: render_storyboard(ir),
        "ink": lambda: render_ink(ir),
        "renpy": lambda: render_renpy(ir),
        "outline": lambda: render_outline(ir),
        "html": lambda: render_html(ir),
    }
    out = renderers[args.format]()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"已写入 {args.out}（{len(out):,} 字符）")
    else:
        print(out)
    return 0


def cmd_outline(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    print(render_outline(ir))
    return 0


def cmd_lore(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    active = ir.lore.compile(args.text, budget_tokens=args.budget)
    print(f"扫描文本：{args.text!r}")
    print(f"预算：{args.budget} tokens\n")
    print(f"激活 {len(active)} / {len(ir.lore.entries)} 条：")
    for e in active:
        tag = "常驻" if e.is_constant else "关键词"
        print(f"  [{tag}] order={e.order:>3} {e.id}")
        print(f"          keys={e.keys} logic={e.logic.value} pos={e.position.value}")
        print(f"          {e.content[:60]}")
    return 0


def cmd_play(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    if args.runs > 1:
        res = randomized_playthroughs(ir, runs=args.runs, turns=args.turns)
        print(f"随机化通关测试：{res['runs']} 次 × {args.turns} 回合\n")
        print(f"  零选项事件     {res['zero_option_events']}")
        print(f"  死路           {res['dead_ends']}")
        print(f"  从未触达的块   {res['never_reached'] or '无'}")
        print("  使用率最高：")
        for sid, ratio in res["overused"]:
            print(f"    {sid:<16} {ratio:.1%}")
        print("\n  Waypoint 触达分布：")
        for wid, hits in res["waypoint_hits"].items():
            bar = "█" * int(40 * hits / max(1, max(res["waypoint_hits"].values())))
            print(f"    {wid:<8} {bar} {hits}")
    else:
        rt = StoryRuntime(ir, seed=args.seed)
        for line in rt.play(turns=args.turns):
            print(line)
        print(f"\n最终品质：{rt.state.qualities}")
    return 0


def cmd_compliance(args: argparse.Namespace) -> int:
    ir = _load(args.ir)
    ledger = ProvenanceLedger()
    # 人工改写比例**只从已有的溯源记录里取**，取不到就按 0 算。
    #
    # 这里原先写死 `human_edit_ratio=0.6` —— 一份合规报告凭空给每个场景
    # 记上「六成人工改写」。对合规工具来说这是**方向性**的错误：
    # 低估 AI 占比会让 100% AI 生成的故事在报告上显示成四成，
    # 而起点撤榜线是 10%、广电要求 AI 参与须显著标识。
    # 少报比多报危险得多，所以默认值必须取**最不利**的 0.0。
    prior = {p.scene_id: p.human_edit_ratio for p in ir.provenance if p.scene_id}
    for s in ir.scenes:
        ledger.record(
            chunk_id=f"chunk_{s.id}", scene_id=s.id, origin=s.origin,
            model_id=s.model_id, prompt_version=s.prompt_version,
            human_edit_ratio=prior.get(s.id, 0.0),
            char_count=len(s.prose or ""),
        )
    ledger.attach(ir)
    rep = ledger.report(ir)
    print(rep.render(f"{ir.title} · AI 参与度与合规报告"))
    if args.json:
        Path(args.json).write_text(rep.to_json(), encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 0


def cmd_process_report(args: argparse.Namespace) -> int:
    """创作过程报告 —— 申诉举证用。

    与 `compliance` 的区别：
        compliance    **占比**（AI 写了多少）—— 免责证据
        process-report **判断**（人做了什么）—— 主张证据

    平台误判时，作者要证明的是「我确实参与了创作」。「AI 只占 8%」
    说不出人做了什么；「我驳回了 14 条 AI 提案」说得出来。
    """
    ir = _load(args.ir)
    rep = build_process_report(ir)
    if args.out:
        Path(args.out).write_text(rep.to_markdown(), encoding="utf-8")
        print(f"已写入 {args.out}（Markdown，可直接作为申诉附件）")
    if args.json:
        Path(args.json).write_text(rep.to_json(), encoding="utf-8")
        print(f"已写入 {args.json}")
    if not args.out and not args.json:
        print(rep.render())
    return 0


def cmd_submit_check(args: argparse.Namespace) -> int:
    """投稿前合规自检。

    与 `compliance` 的区别：
        compliance    只报 **AI 参与度**（溯源计量，回答「占比多少」）
        submit-check  报 **能不能投**（法律义务 + 平台画像 + Loom 检不了的清单）

    退出码：0 = 无硬阻塞；1 = 有硬阻塞（AI 占比越线 / 溯源不可证明）。
    **「待人工确认」不算阻塞** —— 把它算成通过是在宣称 Loom 全查过了，
    算成阻塞则这个命令永远不会有人能用。单列一态是唯一诚实的做法。
    """
    ir = _load(args.ir)
    cl = pre_submit_check(ir)
    print(cl.render())
    if args.json:
        Path(args.json).write_text(cl.to_json(), encoding="utf-8")
        print(f"\n已写入 {args.json}")
    return 1 if cl.blockers else 0


def cmd_templates(args: argparse.Namespace) -> int:
    medium = Medium(args.medium) if args.medium else None
    print(f"可用结构模板{f'（媒介={medium.value}）' if medium else ''}：\n")
    for t in list_templates(medium):
        print(f"  {t.id:<24} {t.name}")
        print(f"    {'':<22} 来源：{t.origin}｜{len(t.beats)} 节拍｜"
              f"校验器 {len(t.validators)}")
        if args.verbose and t.notes:
            print(f"    {'':<22} 备注：{t.notes}")
        print()
    return 0


def cmd_proposals(args: argparse.Namespace) -> int:
    """列出结构提案 —— 它们是**待办**，不是已生效的改动。

    这个命令存在的理由：`CriticLoop` 把结构类问题从「打进日志」升级为
    「生成提案」，但如果作者看不到提案，那升级等于没发生。
    「留给人决策」需要一个作者真的会打开的东西。
    """
    ir = _load(args.ir)
    pending = ir.pending_proposals()
    shown = ir.proposals if args.all else pending

    if not shown:
        print("没有提案。")
        if not ir.proposals:
            print("  （体检没发现结构类问题 —— 干净稿子本来就不该有待办。）")
        return 0

    print(f"《{ir.title}》结构提案：待裁决 {len(pending)} / 共 {len(ir.proposals)}\n")
    for d in shown:
        mark = {"pending": "○", "accepted": "✓", "rejected": "✗", "conflicted": "⚠"}[
            d.status.value
        ]
        print(f"  {mark} [{d.status.value}] {d.id}")
        print(f"      目标   {d.target_card} · 字段 {d.field}")
        print(f"      为什么 {d.rationale}")
        print(f"      建议   {d.after}")
        # 时间/主体：举证字段。有就显示 —— 一条「谁在何时裁的」记录
        # 才是证据；没有时刻的裁决只有态度价值。
        if d.proposed_at:
            print(f"      提出   {d.proposed_at}（{d.source_card}）")
        if d.decided_at:
            print(f"      裁决   {d.decided_at}（{d.decided_by or '未署名'}）")
        print()
    print("裁决：loom decide <ir.json> --accept <id> | --reject <id> | --all --accept")
    print("注：采纳是一个**决定**，不是一次自动改写 —— 采纳后目标字段仍原样，")
    print("    具体怎么改由作者或下一轮生成决定。")
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    """裁决结构提案（一键采纳 / 拒绝）。

    **这是提案生效的唯一入口。** 裁决结果会记入决策遥测
    （采纳率 + 按来源/去向/字段分布），供产品调参 ——
    「作者信不信任 AI 的提案」要么是一个可以查询的数字，要么只是一句感觉。

    ── 两件必须在这里发生、否则裁决等于没发生的事 ──────────────
    1. **盖章**：落下墙钟时刻（`Diff.decided_at`）与裁决主体
       （`Diff.decided_by`）。一条只写着 `rejected` 的记录说不出
       「谁在什么时候驳回了它」—— 那不是证据，是主张。
       时钟在 CLI 这一层取（纯函数层一律不取钟，见 `loom/clock.py`）。
    2. **落盘**：**默认写回原文件**。此前只有传 `--out` 才保存，
       于是最常见的用法（`loom decide ir.json --all`）在进程退出时把
       作者刚做的一堆判断丢得干干净净 —— 人做了判断，系统没记住，
       申诉时这条证据不存在。不落盘的裁决不是裁决。
    """
    ir = _load(args.ir)
    gen = build_generator(offline=True)
    pipe = LoomPipeline(gen)

    if args.all:
        targets = [d.id for d in ir.pending_proposals()]
    else:
        targets = list(args.ids or [])
    if not targets:
        print("没有指定要裁决的提案（用 --all 或给出 id）。")
        return 1

    # 同一次命令 = 同一次操作 = 同一个时刻（见 `decide_all` 的说明）
    wall = wall_iso()
    who = args.by or "human"

    ok = 0
    for did in targets:
        try:
            pipe.decide(
                ir,
                did,
                accept=args.accept,
                decided_at=wall,
                decided_by=who,
                story_at=args.at,
            )
            ok += 1
        except KeyError as exc:
            print(f"  ✗ {exc}")
    verdict = "accepted" if args.accept else "rejected"
    print(f"已裁决 {ok}/{len(targets)} 条 → {verdict}")
    print(f"  采纳率 {pipe.telemetry.accept_rate:.0%}"
          f"（{pipe.telemetry.accepted}/{pipe.telemetry.decisions} 次裁决）")
    print(f"  裁决主体 {who} · 时刻 {wall}")
    # 觉察回显：裁决发生的当下就把累计判断数给作者看。
    # 采纳率（上）是**产品指标**，这一行是**作者的自我觉察** —— 两者目的不同，都要有。
    # 依据 CHI 2026 Reactive Writing，详见 loom/provenance/awareness.py。
    print(f"  {awareness_line(ir)}")

    if not args.no_save:
        dest = Path(args.out) if args.out else Path(args.ir)
        dest.write_text(ir.to_json(), encoding="utf-8")
        print(f"  已落盘 {dest}"
              f"（未裁决的提案不构成证据，落盘才留得住）")
    else:
        print("  ⚠ 已按 --no-save 跳过落盘：本次裁决**不会**被保留。")
    return 0


def cmd_glance(args: argparse.Namespace) -> int:
    """第一分钟速览 —— 一屏可分享的卡片。

    把「顶级内核」搬进「低门槛的壳」：一条命令 → 30 秒 → 一屏可转发。
    默认写在与 ir.json 同目录的 glance.html，并打开浏览器。
    """
    ir = _load(args.ir)
    out = (
        Path(args.out)
        if args.out
        else Path(args.ir).resolve().parent / "glance.html"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_glance(ir), encoding="utf-8")
    print(f"已写入 {out}（一屏速览：大纲 + 三张人物卡 + 体检头三行）")
    if getattr(args, "no_open", False):
        print("  （已按 --no-open 跳过自动打开）")
    else:
        try:
            opened = webbrowser.open(out.resolve().as_uri())
        except Exception:
            opened = False
        print(
            "  🌐 已用默认浏览器打开。" if opened
            else "  （未能自动打开，请手动双击上面的路径。）"
        )
    return 0


def cmd_c2pa(args: argparse.Namespace) -> int:
    """导出 C2PA 内容凭证 manifest（全球合规出口）。

    把中国合规的溯源台账升级为 C2PA 2.x 兼容的内容凭证结构。
    Loom 只生产 manifest，**不签名**（签名需 C2PA 凭证，超出零依赖范围）。
    导出的 JSON 可交由支持 C2PA 的工具签名后嵌入素材元数据。
    """
    ir = _load(args.ir)
    ledger = ProvenanceLedger()
    # 人工改写比例**只从已有的溯源记录里取**，取不到就按 0 算。
    #
    # 这里原先写死 `human_edit_ratio=0.6` —— 一份合规报告凭空给每个场景
    # 记上「六成人工改写」。对合规工具来说这是**方向性**的错误：
    # 低估 AI 占比会让 100% AI 生成的故事在报告上显示成四成，
    # 而起点撤榜线是 10%、广电要求 AI 参与须显著标识。
    # 少报比多报危险得多，所以默认值必须取**最不利**的 0.0。
    prior = {p.scene_id: p.human_edit_ratio for p in ir.provenance if p.scene_id}
    for s in ir.scenes:
        ledger.record(
            chunk_id=f"chunk_{s.id}", scene_id=s.id, origin=s.origin,
            model_id=s.model_id, prompt_version=s.prompt_version,
            human_edit_ratio=prior.get(s.id, 0.0),
            char_count=len(s.prose or ""),
        )
    ledger.attach(ir)
    out = (
        Path(args.out)
        if args.out
        else Path(args.ir).resolve().parent / "c2pa.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ledger.to_c2pa_json(ir), encoding="utf-8")
    print(f"已写入 {out}（C2PA 2.x 内容凭证 manifest，未签名）")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    """把校验器作为「全程序化、无 LLM-judge」的作家工具基准导出。

    差异化于 story-bench（其用 50% LLM-judge 判定）：loom-bench 的所有判定
    都是确定性、可复现、可证伪的。每条校验器带理论出处（docstring 首行）、
    门禁/报表分类、本 IR 上的评估情况。发给评审 / 论文 / 竞品对比用。
    """
    ir = _load(args.ir)
    report = run_all(ir)
    stats = registry_stats()
    rows = []
    for code in available():
        fn = get_validator(code)
        doc = (inspect.getdoc(fn) or "").strip().splitlines()
        source = doc[0].strip() if doc else ""
        gating = code not in REPORTS
        rows.append(
            {
                "code": code,
                "type": "gate" if gating else "report",
                "theory": source,
                "requires": sorted(REQUIRES.get(code, [])),
                "evaluated_on_this_ir": code in report.evaluated,
                "skipped_on_this_ir": code in report.skipped,
            }
        )
    out = {
        "tool": "loom-bench",
        "method": "deterministic structural validators; no LLM judge",
        "isomorphism_with": [
            "NCP-Bench (ICML 2026, YAML 三层 IR)",
            "story-bench (2025, 5 客观故事框架)",
        ],
        "differentiator": (
            "story-bench 用 50% LLM-judge 判定；loom-bench 全程序化、"
            "可复现、可证伪，且不预测作品是否成功。"
        ),
        "gating_count": stats["gating"],
        "report_count": stats["reports"],
        "total": stats["total"],
        "validators": rows,
        "run_on_ir": {
            "title": ir.title,
            "score": report.score(),
            "evaluated": len(report.evaluated),
            "skipped": len(report.skipped),
            "crashed": len(report.crashes),
        },
    }
    target = (
        Path(args.out)
        if args.out
        else Path(args.ir).resolve().parent / "bench.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"已写入 {target}（{stats['total']} 个校验器 · 全程序化 · 无 LLM 评审）"
    )
    return 0


def cmd_api(args: argparse.Namespace) -> int:
    """插件契约入口 —— 把引擎能力以**稳定的 JSON** 暴露给薄客户端。

    为什么不让插件直接解析上面那些命令的人类可读输出：那是**写给眼睛的**，
    随时可以被改得更好读（这是它的本职）。插件一旦依赖它，改文案就会
    **静默**弄坏插件，而且没有任何测试会红 —— 因为插件不在 Python 测试里。

    退出码（插件据此分支，比解析文案可靠）：

        0 = 成功
        1 = 用户侧错误（方法名 / 参数 / 文件问题）
        2 = `--params` 不是合法 JSON
        6 = **Loom 自己崩了**（bug）。与「稿子有缺陷」必须分开：
            一个以 0 退出的崩溃，在脚本与 CI 里读起来和一次成功一模一样。
            （0-5 已被 write/run 占用：3=在等人，4=答案格式，5=计划被拒。）
    """
    params: dict[str, object] = {}
    for key, val in (
        ("ir", args.ir),
        ("format", args.format),
        ("medium", args.medium),
        ("by", args.by),
        ("at", args.at),
        ("out", args.out),
    ):
        if val is not None:
            params[key] = val
    # 布尔开关只在**为真**时才进参数表：默认值由 api.py 的方法签名决定，
    # 这里再写一遍默认值就会有两份真相。
    for key, val in (
        ("all", args.all),
        ("accept", args.accept),
        ("no_save", args.no_save),
        ("meta", args.meta),
        ("chrono", args.chrono),
        ("force_prose", args.force_prose),
    ):
        if val:
            params[key] = True
    if args.id:
        params["ids"] = list(args.id)
    if args.params:
        try:
            extra = json.loads(args.params)
        except json.JSONDecodeError as exc:
            print(f"\n  ✗ --params 不是合法 JSON：{exc}", file=sys.stderr)
            return 2
        if not isinstance(extra, dict):
            print(
                "\n  ✗ --params 必须是一个 JSON 对象，例如 "
                '\'{"all": true}\'',
                file=sys.stderr,
            )
            return 2
        params.update(extra)

    payload = loom_api.call(args.method, params)
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=None if args.compact else 2,
            default=str,
        )
    )
    if payload.get("ok"):
        return 0
    return 6 if loom_api.is_internal(payload) else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loom", description="Loom 叙事编译器")
    # `--version` 必须挂在顶层：打包成 console script 之后，用户第一件事往往
    # 是确认自己装的是哪个版本。argparse 的 version action 会直接打印并退出，
    # 不会掉进「不是已知子命令」的分支。
    p.add_argument("--version", action="version",
                   version=f"loom {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("write", help="想法 -> IR -> 正文（1.0 主命令）")
    w.add_argument("idea", help="一句话想法")
    w.add_argument("--out", help="输出目录")
    w.add_argument("--model", help="LiteLLM 模型名；不填则用离线参考生成器")
    w.add_argument(
        "--generator", choices=["mock", "workbuddy"],
        help="驱动方式：mock=离线桩件（形态对、内容假）；"
             "workbuddy=Loom 把提示词写成待填文件，由 WorkBuddy/人填答案"
             "（无 key 也能产出真内容，且每次调用都可回放）",
    )
    w.add_argument("--medium", default="novel",
                   choices=[m.value for m in Medium])
    w.add_argument("--arc", default="man_in_a_hole",
                   choices=[a.value for a in ArcShape])
    w.add_argument("--template", default="save_the_cat")
    w.add_argument("--scenes", type=int, default=5)
    w.add_argument("--words", type=int, default=800, help="每场目标字数")
    w.add_argument("--force-prose", action="store_true",
                   help="强制生成网文正文（默认按平台合规策略挡住，见 loom/policy.py）")
    w.add_argument("--no-open", action="store_true",
                   help="生成后不自动用浏览器打开报告")
    w.add_argument("--rounds", type=int, default=2, help="体检修订轮数")
    w.set_defaults(func=cmd_write)

    rn = sub.add_parser(
        "run",
        help="自动驾驶：不喊停就一直写，直到 IR 派生的停止判据成立",
    )
    rn.add_argument("idea", help="一句话想法")
    rn.add_argument("--out", help="输出根目录（默认 out/）")
    rn.add_argument("--model", help="LiteLLM 模型名；不填则用离线参考生成器")
    rn.add_argument(
        "--generator", choices=["mock", "workbuddy"],
        help="同 write：mock=离线桩件；workbuddy=把提示词写成待填文件",
    )
    rn.add_argument("--medium", default="novel",
                    choices=[m.value for m in Medium])
    rn.add_argument("--arc", default="man_in_a_hole",
                    choices=[a.value for a in ArcShape])
    rn.add_argument("--template", default="save_the_cat")
    rn.add_argument("--scenes", type=int, default=6, help="目标场数（停止判据之一）")
    rn.add_argument("--words", type=int, default=300, help="每场目标字数")
    # 预算闸：**没有它，「不喊停」就是失控**。这三个轴任一触顶即硬停。
    rn.add_argument("--max-scenes", type=int, default=20)
    rn.add_argument("--max-cost", type=float, default=5.0)
    rn.add_argument("--max-minutes", type=float, default=30.0)
    rn.add_argument("--checkpoint", action="store_true",
                    help="落检查点，崩了可从断点续跑（长跑建议开）")
    rn.add_argument("--resume-from",
                    help="从这份**人工裁决过的** IR 续跑（暂停后必填，"
                         "否则会拿检查点里那份没人裁过的 IR 覆盖你的裁决）")
    rn.set_defaults(func=cmd_run)

    au = sub.add_parser("audience", help="观众模拟")
    au.add_argument("ir")
    au.add_argument("--personas", help="逗号分隔的人格 id；默认按媒介选评审团")
    au.add_argument("--model", help="LiteLLM 模型名")
    au.add_argument("--no-llm", action="store_true", help="只出确定性留存曲线")
    au.add_argument("--json")
    au.set_defaults(func=cmd_audience)

    a = sub.add_parser("audit", help="跑故事体检")
    rc = sub.add_parser("recheck",
                        help="用当前校验器重跑旧 IR，并报出「上次以来变了什么」")
    rc.add_argument("ir")
    rc.add_argument("--snapshot", help="体检快照路径（默认 <ir 名>.audit.json）")
    rc.set_defaults(func=cmd_recheck)
    a.add_argument("ir")
    a.set_defaults(func=cmd_audit)

    pr = sub.add_parser("proposals", help="列出结构提案（待作者裁决）")
    pr.add_argument("ir")
    pr.add_argument("--all", action="store_true", help="含已裁决的")
    pr.set_defaults(func=cmd_proposals)

    dc = sub.add_parser("decide", help="裁决结构提案（一键采纳/拒绝）")
    dc.add_argument("ir")
    dc.add_argument("ids", nargs="*", help="提案 id；配合 --all 时可省略")
    dc.add_argument("--all", action="store_true", help="对全部待裁决提案操作")
    dc.add_argument("--accept", action="store_true", help="采纳（默认拒绝）")
    dc.add_argument("--at", help="故事内时点标签（如「第 3 章」），仅用于产品指标")
    dc.add_argument("--by", help="裁决主体标识（默认 human，用于举证）")
    dc.add_argument("--out", help="另存到指定文件（默认写回原 ir.json）")
    dc.add_argument("--no-save", dest="no_save", action="store_true",
                    help="不落盘（裁决只存在于本次进程内，**不构成证据**）")
    dc.set_defaults(func=cmd_decide)

    r = sub.add_parser("render", help="渲染为各种媒介")
    r.add_argument("ir")
    r.add_argument("-f", "--format", default="text",
                   choices=["text", "fountain", "storyboard", "ink", "renpy",
                            "outline", "html"])
    r.add_argument("-o", "--out")
    r.add_argument("--force-prose", action="store_true",
                   help="强制生成网文正文（默认按平台合规策略挡住，见 loom/policy.py）")
    r.add_argument("--meta", action="store_true", help="在正文中嵌入结构元信息")
    r.add_argument("--chrono", action="store_true", help="按故事时间排序")
    r.set_defaults(func=cmd_render)

    o = sub.add_parser("outline", help="输出大纲（IR 层人工确认）")
    o.add_argument("ir")
    o.set_defaults(func=cmd_outline)

    l = sub.add_parser("lore", help="查看 lore 激活集")
    l.add_argument("ir")
    l.add_argument("--text", required=True)
    l.add_argument("--budget", type=int, default=2048)
    l.set_defaults(func=cmd_lore)

    pl = sub.add_parser("play", help="跑运行时（storylet + director）")
    pl.add_argument("ir")
    pl.add_argument("--runs", type=int, default=1)
    pl.add_argument("--turns", type=int, default=20)
    pl.add_argument("--seed", type=int, default=42)
    pl.set_defaults(func=cmd_play)

    c = sub.add_parser("compliance", help="生成 AI 参与度合规报告")
    c.add_argument("ir")
    c.add_argument("--json")
    c.set_defaults(func=cmd_compliance)

    sc = sub.add_parser("submit-check", help="投稿前合规自检（法律义务 + 平台画像 + 待确认项）")
    sc.add_argument("ir")
    sc.add_argument("--json")
    sc.set_defaults(func=cmd_submit_check)

    pr = sub.add_parser("process-report", help="创作过程报告（人类判断留痕，申诉举证）")
    pr.add_argument("ir")
    pr.add_argument("--out", help="输出 Markdown 文件")
    pr.add_argument("--json")
    pr.set_defaults(func=cmd_process_report)

    t = sub.add_parser("templates", help="列出结构模板")
    t.add_argument("--medium")
    t.add_argument("-v", "--verbose", action="store_true")
    t.set_defaults(func=cmd_templates)

    gl = sub.add_parser("glance", help="第一分钟速览（一屏可分享卡片）")
    gl.add_argument("ir")
    gl.add_argument("--out", help="输出 HTML 路径（默认 <ir 同目录>/glance.html）")
    gl.add_argument("--no-open", action="store_true", help="生成后不自动打开浏览器")
    gl.set_defaults(func=cmd_glance)

    cp = sub.add_parser("c2pa", help="导出 C2PA 内容凭证 manifest（全球合规出口）")
    cp.add_argument("ir")
    cp.add_argument("--out", help="输出 JSON 路径（默认 <ir 同目录>/c2pa.json）")
    cp.set_defaults(func=cmd_c2pa)

    bn = sub.add_parser("bench", help="导出作家工具基准（全程序化，无 LLM-judge）")
    bn.add_argument("ir")
    bn.add_argument("--out", help="输出 JSON 路径（默认 <ir 同目录>/bench.json）")
    bn.set_defaults(func=cmd_bench)

    # 插件契约。**这是给程序用的入口，不是给眼睛用的** —— 参数表刻意做全，
    # 免得薄客户端为了拿一个字段去解析人类可读输出（那就会静默漂移）。
    ap = sub.add_parser(
        "api", help="插件契约：以稳定 JSON 暴露引擎能力（VS Code / Obsidian 薄客户端用）"
    )
    ap.add_argument("method", help="方法名；先跑 `loom api handshake` 看全部签名")
    ap.add_argument("--ir", help="IR 文件路径")
    ap.add_argument("--format", help="渲染格式：text|fountain|storyboard|ink|renpy|outline|html")
    ap.add_argument("--medium", help="templates：按媒介过滤")
    ap.add_argument("--id", action="append", help="decide：提案 id（可重复）")
    ap.add_argument("--all", action="store_true",
                    help="decide：裁决全部待裁决；proposals：连已裁决的一起列")
    ap.add_argument("--accept", action="store_true", default=False, help="decide：采纳")
    ap.add_argument("--reject", dest="accept", action="store_false",
                    help="decide：驳回（默认）")
    ap.add_argument("--by", help="decide：裁决主体署名（默认 human）")
    ap.add_argument("--at", help="decide：故事内时点标签（如「第 3 章」）")
    ap.add_argument("--out", help="decide：写回目标（默认写回 --ir 原文件）")
    ap.add_argument("--no-save", action="store_true",
                    help="decide：跳过落盘（本次裁决**不会**被保留）")
    ap.add_argument("--meta", action="store_true", help="render text：带元信息")
    ap.add_argument("--chrono", action="store_true", help="render text：按时间顺序")
    ap.add_argument("--force-prose", action="store_true", help="render text：强制正文")
    ap.add_argument("--params", help="任意参数，JSON 对象（覆盖上面同名项）")
    ap.add_argument("--compact", action="store_true", help="单行 JSON（管道用）")
    ap.set_defaults(func=cmd_api)

    wb = sub.add_parser("web", help="启动本地网页界面（浏览器里操作 Loom，零依赖）")
    wb.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认仅本机 127.0.0.1）")
    wb.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    wb.add_argument("--out", help="产物根目录（默认 out/）")
    wb.set_defaults(func=cmd_web)

    # `serve` 是 `web` 的别名，照顾习惯「起服务」说法的用户。
    sv = sub.add_parser("serve", help="同 web：启动本地网页界面")
    sv.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认仅本机 127.0.0.1）")
    sv.add_argument("--port", type=int, default=8000, help="端口（默认 8000）")
    sv.add_argument("--out", help="产物根目录（默认 out/）")
    sv.set_defaults(func=cmd_web)

    return p


# ---------------------------------------------------------------------------
# 首跑引导菜单（无参数 + 交互终端时给新手一个入口）
# ---------------------------------------------------------------------------


def _pick(prompt: str, values: list[str], default: str) -> str:
    """让用户在列表里选一个值（支持数字序号，或直接输入 value）。"""
    while True:
        v = input(prompt).strip()
        if not v:
            return default
        try:
            idx = int(v) - 1
        except ValueError:
            if v in values:
                return v
            print("   无效，请重新输入。")
            continue
        if 0 <= idx < len(values):
            return values[idx]
        print(f"   请输入 1-{len(values)} 之间的数字。")


def _int_in(prompt: str, lo: int, hi: int, default: int) -> int:
    while True:
        v = input(prompt).strip()
        if not v:
            return default
        try:
            n = int(v)
        except ValueError:
            print("   请输入数字。")
            continue
        if lo <= n <= hi:
            return n
        print(f"   请输入 {lo}-{hi} 之间的数字。")


def _guided_write() -> int:
    """交互式收集参数后调用 cmd_write（共用同一生成入口，零漂移）。"""
    print("\n   Loom 会生成一版草稿并做结构体检——它指出问题，决定权在你。")
    print("   一句话想法（例如：一个退休教师收到三十年前学生寄来的悔过书）：")
    idea = input("   > ").strip()
    if not idea:
        print("   想法不能为空，回到菜单。")
        return _interactive_menu()
    meds = [m.value for m in Medium]
    print("\n   媒介（回车 = novel 小说）：")
    for i, m in enumerate(meds):
        print(f"     {i + 1}. {m}")
    medium = _pick(f"   选媒介 [1-{len(meds)}]：", meds, "novel")
    arcs = [a.value for a in ArcShape]
    print("\n   情感弧线（回车 = man_in_a_hole）：")
    for i, a in enumerate(arcs):
        print(f"     {i + 1}. {a}")
    arc = _pick(f"   选弧线 [1-{len(arcs)}]：", arcs, "man_in_a_hole")
    tmpls = [t.id for t in list_templates()]
    print("\n   结构模板（回车 = save_the_cat）：")
    for i, t in enumerate(tmpls):
        print(f"     {i + 1}. {t}")
    template = _pick(f"   选模板 [1-{len(tmpls)}]：", tmpls, "save_the_cat")
    scenes = _int_in("   场数 [1-30，回车 = 6]：", 1, 30, 6)
    words = _int_in("   每场字数 [50-5000，回车 = 800]：", 50, 5000, 800)
    ns = argparse.Namespace(
        idea=idea, out=None, model=None, medium=medium,
        arc=arc, template=template, scenes=scenes, words=words,
        force_prose=False, no_open=False, rounds=2,
    )
    return cmd_write(ns)


def _open_existing() -> int:
    base = Path("out")
    hubs = sorted(base.glob("*/loom.html"))
    if not hubs:
        print("\n   还没有生成过故事（out/ 下没有 loom.html）。先选 [2] 生成一个吧。")
        return 0
    print("\n   已生成的枢纽：")
    for i, h in enumerate(hubs):
        print(f"     {i + 1}. {h.parent.name}")
    while True:
        v = input(f"\n   打开哪一个 [1-{len(hubs)}]（q 返回）：").strip().lower()
        if v in ("q", ""):
            return 0
        try:
            idx = int(v) - 1
        except ValueError:
            print("   无效。")
            continue
        if 0 <= idx < len(hubs):
            h = hubs[idx].resolve()
            print(f"\n   打开：{h}")
            try:
                webbrowser.open(h.as_uri())
            except Exception:
                pass
            return 0
        print("   超出范围。")


def _interactive_menu() -> int:
    """`loom`（无参数）在交互终端下给新手一个引导菜单。

    研究结论（§L）：首跑引导 / empty-state / aha-moment 是降低前 30 天流失的
    顶级手段（B 级）。CLI 不该只把「不知道敲什么」的人挡在 argparse 报错外，
    而该给一条可走的路。非交互终端（管道/CI）下不进菜单，避免挂起。
    """
    print()
    print("=" * 56)
    print("  Loom · 叙事编译器（你的对抗性编辑）")
    print("=" * 56)
    print("  Loom 不替你写，也不夸你写得好。")
    print("  它生成一版草稿，再用结构体检指出哪里站不住、哪里要合规，")
    print("  每个决定都交还给你。\n")
    print("  选一种方式开始：\n")
    print("   [1] 在浏览器里操作（推荐，最省事，普通人也能用）")
    print("   [2] 在命令行直接生成一个故事")
    print("   [3] 打开我之前生成过的故事")
    print("   [4] 看全部命令说明")
    print("   [q] 退出")
    while True:
        try:
            choice = input("\n   请输入 1-4 或 q：").strip().lower()
        except EOFError:
            # 「是 TTY 但读不到输入」是真的会发生的：双击起来的窗口跑完就关、
            # 某些 IDE 的终端、stdin 被提前关闭。`isatty()` 挡不住它 ——
            # 挡不住时就会把一条 EOFError traceback 甩给用户，
            # 而用户只是想看一眼这个工具是干什么的。
            print("\n   读不到输入（非交互环境），下面显示全部命令说明：\n")
            build_parser().print_help()
            return 2
        if choice in ("q", "quit", "exit"):
            print("   再见。")
            return 0
        if choice == "1":
            print("\n   正在启动本地网页界面…（按 Ctrl+C 停止）")
            return cmd_web(argparse.Namespace(host="127.0.0.1", port=8000, out=None))
        if choice == "2":
            return _guided_write()
        if choice == "3":
            return _open_existing()
        if choice == "4":
            build_parser().print_help()
            continue
        print("   没看懂，请输入 1-4 或 q。")


def main(argv: list[str] | None = None) -> int:
    """入口。**没有子命令时默认走 `write`。**

    为什么要这个默认：`loom "一句话想法"` 与 `loom write "一句话想法"`
    差的是 6 个字符，但前者是「我知道我想要什么」，后者要求用户
    **先学会本工具的命令结构**。门槛决定采用（F7）——
    InkOS 因本地部署 + 命令行在中文横评里只排第 8，
    Loom 每少一步操作，就多一个人真正用上。

    判定规则刻意保守：**只**在第一个参数既不是已知子命令、
    也不是选项（不以 `-` 开头）时才补 `write`。
    这样 `loom --help` / `loom audit x.json` 的行为完全不受影响。
    """
    parser = build_parser()
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    # 无参数：交互终端给引导菜单（研究结论 §L —— 首跑引导降低流失）；
    # 非交互终端（管道 / CI）不进菜单，避免挂起，改为打印帮助并退出非零。
    if not argv:
        if sys.stdin.isatty():
            return _interactive_menu()
        parser.print_help()
        return 2
    if argv and not argv[0].startswith("-") and argv[0] not in _subcommand_names(parser):
        argv = ["write", *argv]
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


def _subcommand_names(parser: argparse.ArgumentParser) -> frozenset[str]:
    """从 parser **派生**子命令名单，不手抄一份。

    手抄一份名单一定会漂：加一个新子命令时忘了同步，
    `loom <新命令>` 就会被当成「一句话想法」送进 `write`，
    报出一个完全不着调的错误。宁可用 argparse 的私有类型，也不要抄。
    """
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return frozenset(action.choices)
    return frozenset()


if __name__ == "__main__":
    sys.exit(main())
