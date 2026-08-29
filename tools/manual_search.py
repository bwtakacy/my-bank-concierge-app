"""商品マニュアル（Markdown）に対するキーワードベースの検索ツール。

設計ドキュメント 4.3 節の Scout 段階で使用する。ベクトルDB等は使わず、
「## 見出し」単位のチャンクに分割したうえで文字bigramの重なりでスコアリング
するだけの単純な実装とする。デモの主眼は検索精度ではなくアーキテクチャの
可視化であるため、これで十分と判断している。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge" / "products"

# ドメイン名 -> マニュアルファイル名
DOMAIN_FILES = {
    "basic_banking": "basic_banking.md",
    "housing_loan": "housing_loan.md",
    "nisa_toshin": "nisa_toshin.md",
}


@dataclass
class ManualChunk:
    domain: str
    source_file: str
    source_version: str
    heading: str
    text: str


@dataclass
class ManualMetadata:
    domain: str
    source_file: str
    source_version: str
    updated_at: str
    requires_qualification: bool


def _parse_frontmatter(raw: str) -> tuple[dict, str]:
    """先頭の `---` ... `---` ブロックをYAML風に簡易パースする。"""
    meta: dict = {}
    if not raw.startswith("---"):
        return meta, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return meta, raw
    _, fm_block, body = parts
    for line in fm_block.strip().splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.lower() in ("true", "false"):
            meta[key] = value.lower() == "true"
        else:
            meta[key] = value
    return meta, body


def _split_into_chunks(domain: str, source_file: str, source_version: str, body: str) -> list[ManualChunk]:
    chunks: list[ManualChunk] = []
    # "## " で始まる見出し単位に分割（先頭の "# タイトル" 部分は除く）
    sections = re.split(r"^## ", body, flags=re.MULTILINE)
    for section in sections[1:]:
        lines = section.strip().splitlines()
        if not lines:
            continue
        heading = lines[0].strip()
        text = "\n".join(lines[1:]).strip()
        chunks.append(
            ManualChunk(
                domain=domain,
                source_file=source_file,
                source_version=source_version,
                heading=heading,
                text=text,
            )
        )
    return chunks


@cache
def _load_domain(domain: str) -> tuple[ManualMetadata, tuple[ManualChunk, ...]]:
    filename = DOMAIN_FILES[domain]
    path = KNOWLEDGE_DIR / filename
    raw = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(raw)
    version = str(meta.get("version", "unknown"))
    metadata = ManualMetadata(
        domain=domain,
        source_file=filename,
        source_version=version,
        updated_at=str(meta.get("updated_at", "")),
        requires_qualification=bool(meta.get("requires_qualification", False)),
    )
    chunks = tuple(_split_into_chunks(domain, filename, version, body))
    return metadata, chunks


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    if len(s) < 2:
        return {s} if s else set()
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _score(question_bigrams: set[str], chunk: ManualChunk) -> float:
    if not question_bigrams:
        return 0.0
    heading_bg = _bigrams(chunk.heading)
    text_bg = _bigrams(chunk.text)
    # 見出しの一致は本文の一致より重みを高くする
    heading_overlap = len(question_bigrams & heading_bg)
    text_overlap = len(question_bigrams & text_bg)
    return heading_overlap * 2.0 + text_overlap * 1.0


def get_metadata(domain: str) -> ManualMetadata:
    metadata, _ = _load_domain(domain)
    return metadata


def search(domain: str, question: str, top_k: int = 3) -> list[ManualChunk]:
    """質問文とマニュアルチャンクの文字bigram重なりでスコアリングし、
    上位 top_k 件を返す。ヒットが1件もなければ空リストを返す
    （専門エージェント側で「マニュアル抜粋にない」と明示させるため）。
    """
    _, chunks = _load_domain(domain)
    q_bg = _bigrams(question)
    scored = [(_score(q_bg, c), c) for c in chunks]
    scored = [(s, c) for s, c in scored if s > 0]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [c for _, c in scored[:top_k]]
