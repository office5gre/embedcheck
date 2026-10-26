"""embedcheck —— 核对向量库里的内容与来源是否还对得上。

设计原则：
1. **文档改了，向量库不会自己知道**。所以要拿库里的条目去比对来源现状。
2. **只说「该更新哪些」，不重建索引**。重建是另一件事，风险也更大。
3. **分清三种情况**：内容变了、来源没了、重复入库。三者的处理完全不同。

仅依赖 Python 标准库。

用法:
    python embedcheck.py --help
    python embedcheck.py --store store.jsonl --source ./docs
    python embedcheck.py --store store.jsonl --source ./docs --json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

# ---------------------------------------------------------------------------
# 指纹
# ---------------------------------------------------------------------------

# 归一化后取指纹：去掉空白与标点，避免格式变化被误判成内容变化
PUNCT_RE = re.compile(r"[\s，。！？；：、,.!?;:（）()\[\]【】「」\"'“”‘’…—\-]+")


def normalize(text: str) -> str:
    """归一化文本，用于比对内容是否真的变了。"""
    return PUNCT_RE.sub("", (text or "")).lower()


def fingerprint(text: str) -> str:
    """归一化后取 sha256。"""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 输入
# ---------------------------------------------------------------------------

def load_store(path: str) -> list[dict]:
    """读向量库条目清单。

    每条至少要有：id、content、source（来源文件路径）。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
    except OSError as e:
        raise ValueError(f"读不了 {path}：{e}") from e

    if not raw:
        return []
    if raw.startswith("["):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON 解析失败：{e}") from e
        return [x for x in data if isinstance(x, dict)]

    rows: list[dict] = []
    for lineno, line in enumerate(raw.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"第 {lineno} 行 JSON 解析失败：{e}") from e
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def load_sources(root: str) -> dict[str, str]:
    """读来源目录下所有文本文件的内容。"""
    out: dict[str, str] = {}
    if os.path.isfile(root):
        try:
            with open(root, "r", encoding="utf-8") as f:
                out[os.path.basename(root)] = f.read()
        except OSError as e:
            raise ValueError(f"读不了来源 {root}：{e}") from e
        return out

    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace("\\", "/")
            try:
                with open(path, "r", encoding="utf-8") as f:
                    out[rel] = f.read()
            except (OSError, UnicodeDecodeError):
                # 二进制文件之类直接跳过，不算缺失
                continue
    return out


# ---------------------------------------------------------------------------
# 核对
# ---------------------------------------------------------------------------

def check(store: list[dict], sources: dict[str, str],
          id_field: str, content_field: str, source_field: str) -> dict:
    """核对向量库与来源的对应关系。"""
    changed: list[dict] = []
    orphaned: list[dict] = []
    duplicated: list[dict] = []
    ok: list[dict] = []

    # 同一来源里的重复入库
    by_source: dict[str, list[dict]] = defaultdict(list)
    by_content: dict[str, list[dict]] = defaultdict(list)

    for entry in store:
        src = str(entry.get(source_field, ""))
        content = str(entry.get(content_field, ""))
        eid = str(entry.get(id_field, ""))

        by_source[src].append(entry)
        by_content[fingerprint(content)].append(entry)

        # 来源是否还在
        matched = None
        if src not in sources:
            # 来源可能用绝对路径或不同分隔符，试着再找一次
            alt = src.replace("\\", "/")
            matched = next((k for k in sources if k.replace("\\", "/") == alt), None)
            if matched is None:
                orphaned.append({
                    "id": eid,
                    "source": src,
                    "reason": "来源文件已不存在",
                })
                continue
        else:
            matched = src

        # 内容是否还对得上
        src_fp = fingerprint(sources[matched])
        entry_fp = fingerprint(content)
        if entry.get("source_fingerprint") and \
                entry["source_fingerprint"] == src_fp:
            ok.append({"id": eid, "source": matched})
            continue

        if entry_fp and src_fp:
            if entry_fp == src_fp:
                # 与来源完全一致，只是没登记指纹
                ok.append({"id": eid, "source": matched})
                continue
            # 条目内容与来源不一致
            if _overlaps(content, sources[matched]):
                changed.append({
                    "id": eid,
                    "source": matched,
                    "reason": "内容有改动（来源仍在，但文本已变）",
                    "similarity": round(_overlap_ratio(content, sources[matched]), 4),
                })
            else:
                changed.append({
                    "id": eid,
                    "source": matched,
                    "reason": "内容与来源对不上",
                    "similarity": round(_overlap_ratio(content, sources[matched]), 4),
                })
        else:
            changed.append({
                "id": eid,
                "source": matched,
                "reason": "来源内容为空或无法比对",
            })

    # 重复入库
    for src, entries in by_source.items():
        if len(entries) > 1:
            fps = Counter(fingerprint(str(e.get(content_field, ""))) for e in entries)
            exact = sum(c for c in fps.values() if c > 1)
            duplicated.append({
                "source": src,
                "count": len(entries),
                "exact": exact,
                "ids": [str(e.get(id_field, "")) for e in entries],
            })

    # 完全同内容不同 id
    same_content: list[dict] = []
    for fp, entries in by_content.items():
        if len(entries) > 1:
            same_content.append({
                "count": len(entries),
                "ids": [str(e.get(id_field, "")) for e in entries],
            })

    # 来源里有但库里没有的：新增内容没入库
    ingested_sources = set()
    for entry in store:
        src = str(entry.get(source_field, ""))
        alt = src.replace("\\", "/")
        match = next((k for k in sources if k.replace("\\", "/") == alt), None)
        if match:
            ingested_sources.add(match)
    not_ingested = sorted(set(sources) - ingested_sources)

    return {
        "total": len(store),
        "changed": changed,
        "orphaned": orphaned,
        "duplicated": duplicated,
        "same_content": same_content,
        "not_ingested": not_ingested,
        "in_sync": len(changed) + len(orphaned),
        "summary": {
            "changed_count": len(changed),
            "orphaned_count": len(orphaned),
            "duplicate_source_count": len(duplicated),
            "same_content_count": len(same_content),
            "not_ingested_count": len(not_ingested),
        },
    }


def _overlaps(a: str, b: str) -> bool:
    """判断两段文本是否有交集。"""
    return _overlap_ratio(a, b) > 0.0


def _overlap_ratio(a: str, b: str) -> float:
    """用字符集合的 Jaccard 估个相似度。"""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    sa, sb = set(na), set(nb)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render(result: dict) -> str:
    out: list[str] = []
    s = result["summary"]
    out.append("向量库与来源同步核对")
    out.append("=" * 60)
    out.append(f"条目数 {result['total']}")
    out.append("")

    if result["orphaned"]:
        out.append(f"★ 来源已删除（{s['orphaned_count']} 条）：")
        for o in result["orphaned"]:
            out.append(f"  · {o['id']}  ← {o['source']}")
        out.append("")

    if result["changed"]:
        out.append(f"★ 内容已变（{s['changed_count']} 条）：")
        for c in result["changed"]:
            sim = (f"相似度 {c['similarity']:.2f}"
                   if "similarity" in c else "")
            out.append(f"  · {c['id']}  ← {c['source']}  {c['reason']} {sim}")
        out.append("")

    if result["duplicated"]:
        out.append(f"★ 重复入库（{s['duplicate_source_count']} 个来源）：")
        for d in result["duplicated"]:
            out.append(f"  · {d['source']}  入库 {d['count']} 次"
                       f"（其中 {d['exact']} 条内容完全相同）")
        out.append("")

    if result["same_content"]:
        out.append(f"内容完全相同的条目（{s['same_content_count']} 组）：")
        for sc in result["same_content"]:
            out.append(f"  · {sc['count']} 条：{', '.join(sc['ids'][:6])}")
        out.append("")

    if result["not_ingested"]:
        out.append(f"来源里有但库里没有（{s['not_ingested_count']} 个文件）：")
        for n in result["not_ingested"][:15]:
            out.append(f"  · {n}")
        if len(result["not_ingested"]) > 15:
            out.append(f"  …（还有 {len(result['not_ingested']) - 15} 个）")
        out.append("")

    if not (result["changed"] or result["orphaned"] or result["duplicated"]
            or result["not_ingested"]):
        out.append("向量库与来源一致，没有需要更新的条目。")
        out.append("")
        out.append("注：本工具只核对，不重建索引。")
        return "\n".join(out).rstrip()

    out.append("处置建议：")
    if result["orphaned"]:
        out.append("  · 来源已删的条目：从库里移除")
    if result["changed"]:
        out.append("  · 内容已变的条目：按最新来源重新入库")
    if result["duplicated"]:
        out.append("  · 重复入库的条目：保留一条，其余移除")
    if result["not_ingested"]:
        out.append("  · 没入库的来源：新建条目")
    out.append("")
    out.append("注：本工具只核对，不重建索引。")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="embedcheck",
        description="核对向量库里的内容与来源是否还对得上（仅依赖标准库）",
        epilog=(
            "向量库清单（JSONL）：\n"
            "  {\"id\":\"doc1#3\",\"content\":\"...\",\"source\":\"guide.md\"}\n"
            "  python embedcheck.py --store store.jsonl --source ./docs\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--store", required=True, help="向量库条目清单")
    ap.add_argument("--source", required=True, help="来源目录或文件")
    ap.add_argument("--id-field", default="id", help="条目 id 字段")
    ap.add_argument("--content-field", default="content", help="内容字段")
    ap.add_argument("--source-field", default="source", help="来源字段")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args(argv)

    try:
        store = load_store(args.store)
        sources = load_sources(args.source)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    if not store:
        print("向量库清单是空的。", file=sys.stderr)
        return 2

    result = check(store, sources, args.id_field, args.content_field,
                   args.source_field)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(render(result))
    return 1 if result["in_sync"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
