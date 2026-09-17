"""拉取叙事生成 / 计算叙事学论文的**真实引用数**（OpenAlex，免费无需 key）。

为什么要有这个脚本：文档里的引用数是「手抄就会漂」的典型 ——
写的时候对，过半年就错，而且**没有任何测试抓得到**（它只是散文里的一个数字）。
凡是这种数字，都应该能从单一来源重新推导。改文档前跑一次这个脚本对齐。

用法：
    python scripts/fetch_citations.py              # 全部
    python scripts/fetch_citations.py --json out/  # 落盘
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.openalex.org/works"

# (标识, 标题检索串)。用 **title.search** 而不是全文 search ——
# 第一版用全文检索时，「Plan-and-Write」命中了一篇马来西亚公共私营合作论文
# （16193 次引用），「StoryER」命中了 Visual Genome（5310）。
# 错的数字写进文档比没有数字更糟：它会让整份清单失去可信度。
# 因此这里改用标题检索，并加一道**匹配可疑**的自动告警（见 _overlap）。
QUERIES: list[tuple[str, str]] = [
    ("Riedl & Young · IPOCL", "Narrative Planning: Balancing Plot and Character"),
    ("Reagan · 六弧线", "The emotional arcs of stories are dominated by six basic shapes"),
    # 标题里的 ç 会让 OpenAlex 查不到 —— 用无重音写法（已验证：409 次引用）
    ("Mateas & Stern · Façade", "Facade: An Experiment in Building a Fully-Realized Interactive Drama"),
    ("Weyhrauch · Guiding Interactive Drama", "Guiding interactive drama"),
    ("Ware & Young · CPOCL", "CPOCL: A Narrative Planner Supporting Conflict"),
    ("Bae & Young · Surprise", "A Computational Model of Narrative Generation for Surprise"),
    ("Kreminski & Wardrip-Fruin · Storylets", "Sketching a Map of the Storylets Design Space"),
    ("Mostafazadeh · ROCStories", "A Corpus and Cloze Evaluation for Deeper Understanding of Commonsense Stories"),
    ("DeepMind · Dramatron", "Co-Writing Screenplays and Theatre Scripts with Language Models"),
    ("Re3", "Re3: Generating Longer Stories With Recursive Reprompting and Revision"),
    ("Fan · 分层神经故事生成", "Hierarchical Neural Story Generation"),
    ("Yao · Plan-and-Write", "Plan-and-Write: Towards Better Automatic Storytelling"),
    ("Guan · 故事结局生成", "Story Ending Generation with Incremental Encoding and Commonsense Knowledge"),
    ("BooookScore", "BooookScore: A systematic exploration of book-length summarization"),
    ("Toubia · 故事形状预测成功", "How quantifying the shape of stories predicts their success"),
    ("Boyd · narrative arc", "The narrative arc: Revealing core narrative structures through text analysis"),
    ("Goh & Barabási · burstiness", "Burstiness and memory in complex systems"),
    ("Pérez y Pérez · MEXICA", "MEXICA: a computer model of creativity in writing"),
    ("RecurrentGPT", "RecurrentGPT: Interactive Generation of (Arbitrarily) Long Text"),
    ("LitBench", "LitBench: A Benchmark and Dataset for Reliable Evaluation"),
]


def _tokens(text: str) -> set[str]:
    return {t for t in "".join(
        ch.lower() if ch.isalnum() else " " for ch in (text or "")
    ).split() if len(t) > 2}


def _overlap(query: str, title: str) -> float:
    """查询词与命中标题的词重合率。低 = 命中的多半不是这篇。"""
    q, t = _tokens(query), _tokens(title)
    if not q:
        return 0.0
    return len(q & t) / len(q)


def fetch(label: str, query: str) -> dict:
    params = urllib.parse.urlencode({
        "filter": f"title.search:{query}",
        "per_page": "1",
        "select": "title,cited_by_count,publication_year,doi",
    })
    try:
        with urllib.request.urlopen(f"{API}?{params}", timeout=30) as r:
            data = json.load(r)
    except Exception as exc:  # 网络/限流都归类为查不到，不假装成功
        return {"label": label, "error": f"{type(exc).__name__}: {exc}"[:80]}
    results = data.get("results") or []
    if not results:
        return {"label": label, "error": "OpenAlex 无结果"}
    top = results[0]
    row = {
        "label": label,
        "title": top.get("title") or "",
        "citations": top.get("cited_by_count"),
        "year": top.get("publication_year"),
        "doi": top.get("doi") or "",
    }
    # 命中的标题和查的标题词重合太低 ⇒ 报「匹配可疑」，别让人拿去当真数字用
    score = _overlap(query, row["title"])
    row["match_score"] = round(score, 2)
    if score < 0.5:
        row["suspect"] = True
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description="拉取论文真实引用数（OpenAlex）")
    ap.add_argument("--json", metavar="DIR", help="把结果写入 <DIR>/citations.json")
    args = ap.parse_args()

    rows = []
    for label, query in QUERIES:
        rows.append(fetch(label, query))
        time.sleep(0.35)  # OpenAlex 有礼貌即可，别把免费额度打满

    rows.sort(key=lambda r: -(r.get("citations") or -1))

    print("叙事生成 / 计算叙事学 · 真实引用数（OpenAlex）")
    print("=" * 104)
    print(f"{'标识':34s} {'引用':>6s} {'年份':>5s}  OpenAlex 匹配到的标题")
    print("-" * 104)
    for r in rows:
        if "error" in r:
            print(f"{r['label']:34s} {'—':>6s} {'—':>5s}  ⚠ {r['error']}")
            continue
        flag = "  ⚠ 匹配可疑" if r.get("suspect") else ""
        print(f"{r['label']:34s} {r['citations']:6d} {str(r['year'] or '-'):>5s}  {r['title'][:46]}{flag}")
    print("-" * 104)
    ok = [r for r in rows if "citations" in r]
    print(f"查到 {len(ok)}/{len(rows)} 条。口径：OpenAlex cited_by_count，标题检索。")
    print("引用数是**量级判据**，不是精确值：同一篇可能有 arXiv 预印本与正式版两条记录，"
          "OpenAlex 也可能只收录其一。")

    if args.json:
        out = Path(args.json)
        out.mkdir(parents=True, exist_ok=True)
        (out / "citations.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n已写入 {out / 'citations.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
