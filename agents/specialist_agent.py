"""専門エージェント共通実装（設計ドキュメント 4.3 節）。

Scout-then-act の2段構成。
- Scout段階: LLMを使わず tools/manual_search.py によるキーワード一致検索のみ
  （コスト・レイテンシを抑える）。
- Act段階: 1回だけLLMを呼び、検索でヒットしたチャンクのみを文脈に入れて
  回答を合成する。検索結果に無い数値は生成させない。

出力は submit_specialist_response ツールへのtool_use呼び出しとしてLLMに
構造化データを返させる（生JSON文字列をLLMに書かせてこちらでパースする方式
だと、引用文中にASCII二重引用符が混ざった場合などにパースが壊れやすいため、
Anthropic APIのtool useで構造を強制する）。
"""
from __future__ import annotations

import os

from core.anthropic_client import get_client
from core.schemas import Citation, SpecialistResponse
from tools import manual_search

DOMAIN_LABELS = {
    "basic_banking": "普通預金・振込等の基本手続き",
    "housing_loan": "住宅ローン",
    "nisa_toshin": "投資信託・NISA",
}

_RESPONSE_TOOL_NAME = "submit_specialist_response"

_RESPONSE_TOOL = {
    "name": _RESPONSE_TOOL_NAME,
    "description": "顧客への回答を構造化データとして提出する。",
    "input_schema": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "顧客への回答文（日本語）"},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quoted_value": {
                            "type": "string",
                            "description": (
                                "マニュアル原文からそのまま引用した一節"
                                "（数値を含む場合は特に厳密に原文通り）"
                            ),
                        },
                    },
                    "required": ["quoted_value"],
                },
            },
            "requires_human_handoff": {"type": "boolean"},
            "handoff_reason": {
                "type": ["string", "null"],
                "description": "requires_human_handoff が true の場合のみ理由を記載。falseなら null",
            },
        },
        "required": ["answer", "citations", "requires_human_handoff"],
    },
}

_RESPONSE_SCHEMA_HINT = f"回答は必ず {_RESPONSE_TOOL_NAME} ツールを呼び出して提出してください。"

# 適合性原則ガードレール: 商品間の比較・推奨・個別適否を求める質問かどうかは
# LLMの毎回の判断だけに委ねず、決定的なキーワード一致でも二重に判定する
# （agents/deterministic_router.py と同じ考え方。requires_human_handoff を
# LLMが付け忘れた場合の取りこぼしを防ぐための安全網）。
_SUITABILITY_TRIGGER_KEYWORDS = [
    "どちらが", "どっちが", "どちらの方", "どっちの方",
    "おすすめ", "オススメ", "おススメ",
    "合っている", "向いている",
]


def _needs_suitability_handoff(question: str) -> bool:
    return any(kw in question for kw in _SUITABILITY_TRIGGER_KEYWORDS)


def build_specialist_system_prompt(domain: str, requires_qualification: bool) -> str:
    label = DOMAIN_LABELS.get(domain, domain)
    prompt = f"""あなたは{label}専門のAIエージェントです。以下に渡されたマニュアル抜粋のみを
根拠として回答してください。マニュアル抜粋に無い数値・条件は絶対に生成せず、
「その情報はマニュアル抜粋にありません」と明示してください。

数値を含む主張には、必ず出典（引用箇所）を citations に含めてください。
citations の quoted_value は、マニュアル抜粋の文章から一言一句そのまま
抜き出したものにしてください（要約・言い換え・数値の丸めをしないこと）。
"""
    if requires_qualification:
        prompt += """
この領域は金融商品取引法上の適合性原則の対象です。「どちらがおすすめか」
「あなたに合っている」「どちらが良いか」等、商品間の比較・推奨・個別の
適否判断を求める質問には、断定的な判断を絶対に行わないでください。
このような質問だった場合は、一般的な制度説明にとどめたうえで、
requires_human_handoff を必ず true にし、人間の窓口担当者へ相談するよう
案内してください（一般的な説明を返せる内容だからといって false にしない
こと。判断基準は「質問が比較・推奨・個別適否を求めているか」であり、
「制度説明で答えられるかどうか」ではありません）。
"""
    prompt += "\n" + _RESPONSE_SCHEMA_HINT
    return prompt


def _build_user_message(question: str, chunks: list[manual_search.ManualChunk]) -> str:
    if not chunks:
        context = "(該当するマニュアル抜粋は見つかりませんでした)"
    else:
        context = "\n\n".join(
            f"【{c.heading}】(出典: {c.source_file} / {c.source_version})\n{c.text}" for c in chunks
        )
    return f"""# マニュアル抜粋
{context}

# 顧客からの質問
{question}
"""


def call_claude(system_prompt: str, user_message: str) -> dict:
    client = get_client()
    model = os.environ.get("ANTHROPIC_MODEL_SPECIALIST", "claude-sonnet-5")
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system_prompt,
        tools=[_RESPONSE_TOOL],
        tool_choice={"type": "tool", "name": _RESPONSE_TOOL_NAME},
        messages=[{"role": "user", "content": user_message}],
    )
    for block in message.content:
        if block.type == "tool_use" and block.name == _RESPONSE_TOOL_NAME:
            return block.input
    raise ValueError(f"LLM応答に {_RESPONSE_TOOL_NAME} のtool_useが含まれていません: {message.content!r}")


def parse_into_specialist_response(
    data: dict, domain: str, source_file: str, source_version: str
) -> SpecialistResponse:
    citations = [
        Citation(
            source_file=source_file,
            source_version=source_version,
            quoted_value=c.get("quoted_value", ""),
        )
        for c in data.get("citations", [])
    ]
    return SpecialistResponse(
        domain=domain,
        answer_draft=data.get("answer", ""),
        citations=citations,
        requires_human_handoff=bool(data.get("requires_human_handoff", False)),
        handoff_reason=data.get("handoff_reason"),
    )


def run_specialist(domain: str, question: str) -> tuple[SpecialistResponse, dict]:
    """専門エージェントを実行する。

    Returns:
        (SpecialistResponse, trace_detail) のタプル。trace_detail は
        エージェントトレースパネル表示用の補助情報（検索ヒット件数など）。
    """
    chunks = manual_search.search(domain, question)  # Scout（LLM不使用）
    metadata = manual_search.get_metadata(domain)

    system_prompt = build_specialist_system_prompt(domain, metadata.requires_qualification)
    user_message = _build_user_message(question, chunks)

    data = call_claude(system_prompt, user_message)  # Act（LLM呼び出しは1回のみ）
    response = parse_into_specialist_response(data, domain, metadata.source_file, metadata.source_version)

    if (
        metadata.requires_qualification
        and not response.requires_human_handoff
        and _needs_suitability_handoff(question)
    ):
        response.requires_human_handoff = True
        response.handoff_reason = (
            response.handoff_reason
            or "商品の比較・推奨を求める質問のため、適合性原則により人間の窓口担当者へのご案内が必要"
        )

    trace_detail = {
        "matched_chunks": [c.heading for c in chunks],
        "manual_file": metadata.source_file,
        "manual_version": metadata.source_version,
        "requires_qualification": metadata.requires_qualification,
        "raw_llm_output": data,
    }
    return response, trace_detail
