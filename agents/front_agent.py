"""フロントエージェント（設計ドキュメント 4.2 節）。

顧客との唯一の対話窓口。役割は対話管理・意図の要約・専門エージェントの
呼び出し（Agent-as-Tool）・検証結果を踏まえた最終応答の組み立て。
専門エージェントを「対話相手」ではなく「呼べば結果を返すツール」として
扱うことが設計上の核であり、専門エージェント側に会話の主導権を渡さない。

各ターンの処理順序:
  1. 決定的ルーター（LLM不使用）で高リスク意図をチェック → ヒットしたら
     専門エージェントを一切呼ばずに即エスカレーション。
  2. ヒットしなければ、Claudeのtool useで専門エージェントをツールとして
     宣言し、LLMに動的ルーティングさせる。
  3. 専門エージェントの回答は検証エージェントで機械照合してから、
     フロントエージェントが自分の言葉で顧客向けに整えて最終回答を組み立てる。
"""
from __future__ import annotations

import json
import os
import re

from agents import deterministic_router, specialist_agent, verify_agent
from core import escalation
from core.anthropic_client import get_client
from core.audit_log import AuditLog

# ごく稀に、モデルが正規のtool_useブロックを発行せず、`<invoke name="...">`
# という旧式のテキスト形式でツール呼び出しを試みてしまうことがある
# （tool_useは1件も含まれず、テキストとしてこのタグ文字列だけが返る）。
# この場合そのまま最終回答として顧客に返すと壊れた文字列になるため、
# 検出して同じリクエストをリトライする。
_HALLUCINATED_TOOL_CALL_RE = re.compile(r"<invoke\s+name=")
MAX_NO_TOOL_RETRIES = 3

TOOL_TO_DOMAIN = {
    "consult_basic_banking": "basic_banking",
    "consult_housing_loan": "housing_loan",
    "consult_nisa_toshin": "nisa_toshin",
}

SPECIALIST_TOOLS = [
    {
        "name": "consult_basic_banking",
        "description": "普通預金・振込等の基本手続きについて、専門エージェントに問い合わせる。",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "consult_housing_loan",
        "description": "住宅ローン・各種ローンについて、専門エージェントに問い合わせる。",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "consult_nisa_toshin",
        "description": (
            "投資信託・NISAについて、専門エージェントに問い合わせる。適合性原則の対象領域で"
            "あるため、断定的な推奨は専門エージェント側で行わない前提。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
]

FRONT_SYSTEM_PROMPT = """あなたは銀行窓口の受付コンシェルジュAIです。顧客との対話窓口はあなた一人であり、
専門エージェントは「呼び出せば回答を返すツール」として扱ってください。
専門エージェントに会話そのものを委ねたり、専門エージェントの回答をそのまま丸ごと
顧客に転送したりせず、必ずあなたの言葉で顧客向けに整えて伝えてください。

数値（金利・手数料等）を含む回答は、専門エージェントの回答に付随する出典
（citations）をそのまま保持し、検証エージェントのチェックを経てから顧客に
提示してください。検証で不一致が見つかった場合は、訂正後の値を使うか、
不明な場合はその旨を正直に伝えてください。

相続・解約・苦情など高リスクな意図の場合は、専門エージェントに問い合わせず、
その場で「担当の行員におつなぎします」と伝えてエスカレーションしてください。

投資信託・NISA・保険について「どちらがいいか」「おすすめは」等、断定的な
判断を求められた場合も、必ず一度 consult_nisa_toshin 等の専門エージェントに
問い合わせてください（適合性原則の対象領域のため、断定的な推奨を行うかどうか
の判断は専門エージェント側のガードレールに委ねる。あなた自身の判断で専門
エージェントの呼び出しを省略しないこと）。専門エージェントの実行結果が
"escalation_required" だった場合は、そのままエスカレーションの案内をしてください。

ツール（consult_xxx）の実行結果はJSON文字列で返されます。status フィールドを
必ず確認してください。
- "verified": answer の内容を、出典(citations)の裏付けがある事実として顧客に案内してよい。
- "corrected": answer は検証エージェントが商品マスタに基づき訂正済みの数値です。
  この正しい数値を使って回答してください。
- "escalation_required": customer_message の内容（または同趣旨の文面）を伝え、
  それ以上の数値の断定は行わず、担当の行員へのご案内で会話を締めくくってください。

いずれの場合も、ツールの結果をそのまま転記せず、丁寧な窓口口調のひとつの
回答文にまとめ直してください。
"""

MAX_TOOL_ITERATIONS = 4


def consult_specialist(domain: str | None, question: str, audit_log: AuditLog, model_id: str | None = None) -> str:
    """専門エージェントを呼び出し、検証エージェントでチェックしたうえで、
    フロントエージェント（LLM）に渡すためのJSON文字列を返す。

    Anthropicクライアントを必要とするのは専門エージェントのAct段階
    （specialist_agent.run_specialist 内部）のみであり、この関数自体は
    front_agent の tool-use ループから独立してテストできる
    （設計ドキュメント7章のシナリオ3: 専門エージェントをモックして
    LLM呼び出しを介さずに検証エージェント単体のロジックをテストする、に対応）。
    """
    if domain is None:
        return json.dumps({"status": "error", "reason": "unknown_domain"}, ensure_ascii=False)

    response, trace = specialist_agent.run_specialist(domain, question)
    audit_log.record(
        agent_id=f"specialist:{domain}",
        action="specialist_answer",
        model_id=model_id or os.environ.get("ANTHROPIC_MODEL_SPECIALIST"),
        manual_version=trace["manual_version"],
        detail={
            "answer_draft": response.answer_draft,
            "citations": [c.__dict__ for c in response.citations],
            "requires_human_handoff": response.requires_human_handoff,
            "handoff_reason": response.handoff_reason,
            "matched_chunks": trace["matched_chunks"],
            "manual_file": trace["manual_file"],
        },
    )

    if response.requires_human_handoff:
        esc = escalation.escalate(
            "suitability_guardrail",
            response.handoff_reason or "適合性原則等によりAIでの断定判断を回避",
        )
        audit_log.record(
            agent_id="front_agent",
            action="escalate",
            detail={"reason_category": esc.reason_category, "reason_detail": esc.reason_detail},
        )
        return json.dumps(
            {
                "status": "escalation_required",
                "reason": esc.reason_detail,
                "customer_message": esc.customer_message,
                "specialist_general_info": response.answer_draft,
            },
            ensure_ascii=False,
        )

    verification = verify_agent.verify(response)
    audit_log.record(
        agent_id="verify_agent",
        action="verify",
        manual_version=trace["manual_version"],
        detail={
            "ok": verification.ok,
            "checked_claims": verification.checked_claims,
            "mismatches": verification.mismatches,
            "corrected_answer": verification.corrected_answer,
        },
    )

    citations_text = [f"{c.source_file}({c.source_version}): 「{c.quoted_value}」" for c in response.citations]

    if verification.ok:
        return json.dumps(
            {"status": "verified", "answer": response.answer_draft, "citations": citations_text},
            ensure_ascii=False,
        )

    if verification.corrected_answer:
        return json.dumps(
            {
                "status": "corrected",
                "answer": verification.corrected_answer,
                "citations": citations_text,
            },
            ensure_ascii=False,
        )

    esc = escalation.escalate("verification_unresolved", "; ".join(verification.mismatches))
    audit_log.record(
        agent_id="front_agent",
        action="escalate",
        detail={"reason_category": esc.reason_category, "reason_detail": esc.reason_detail},
    )
    return json.dumps(
        {
            "status": "escalation_required",
            "reason": esc.reason_detail,
            "customer_message": esc.customer_message,
        },
        ensure_ascii=False,
    )


class FrontAgent:
    """1会話セッション分のフロントエージェント状態を保持する。"""

    def __init__(self, audit_log: AuditLog | None = None) -> None:
        self.client = get_client()
        self.model = os.environ.get("ANTHROPIC_MODEL_FRONT", "claude-sonnet-5")
        self.audit_log = audit_log if audit_log is not None else AuditLog()
        self.messages: list[dict] = []

    def handle_user_message(self, user_message: str) -> str:
        """顧客からの1メッセージを処理し、最終回答文字列を返す。"""
        category = deterministic_router.check_high_risk(user_message)
        if category:
            self.audit_log.record(
                agent_id="deterministic_router",
                action="route",
                detail={
                    "decision": "high_risk_escalation",
                    "category": category,
                    "user_message": user_message,
                },
            )
            result = escalation.escalate("high_risk_intent", f"高リスク意図カテゴリ: {category}")
            self.audit_log.record(
                agent_id="front_agent",
                action="escalate",
                detail={
                    "reason_category": result.reason_category,
                    "reason_detail": result.reason_detail,
                },
            )
            self.messages.append({"role": "user", "content": user_message})
            self.messages.append({"role": "assistant", "content": result.customer_message})
            return result.customer_message

        self.audit_log.record(
            agent_id="deterministic_router",
            action="route",
            detail={"decision": "no_high_risk_hit", "user_message": user_message},
        )

        self.messages.append({"role": "user", "content": user_message})
        final_text = self._run_tool_loop()
        self.messages.append({"role": "assistant", "content": final_text})
        return final_text

    def _create_message(self):
        """通常のAPI呼び出し。tool_useが1件もなく、かつテキストが旧式の
        `<invoke ...>` ツール呼び出しタグに見える場合だけ、同じリクエストを
        リトライする（本物のtool_useが返るまで、または規定回数まで）。"""
        response = None
        for _ in range(1 + MAX_NO_TOOL_RETRIES):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=FRONT_SYSTEM_PROMPT,
                tools=SPECIALIST_TOOLS,
                messages=self.messages,
            )
            has_tool_use = any(block.type == "tool_use" for block in response.content)
            if has_tool_use:
                return response
            text = "".join(block.text for block in response.content if block.type == "text")
            if not _HALLUCINATED_TOOL_CALL_RE.search(text):
                return response
        return response

    def _run_tool_loop(self) -> str:
        for _ in range(MAX_TOOL_ITERATIONS):
            response = self._create_message()

            tool_uses = [block for block in response.content if block.type == "tool_use"]
            text_blocks = [block.text for block in response.content if block.type == "text"]

            if not tool_uses:
                return "".join(text_blocks).strip() or "申し訳ございません、回答を生成できませんでした。"

            # tool_use を含むassistantターンをそのまま履歴に積む（API仕様上必須）
            self.messages.append({"role": "assistant", "content": response.content})

            tool_result_blocks = []
            for tool_use in tool_uses:
                domain = TOOL_TO_DOMAIN.get(tool_use.name)
                question = (tool_use.input or {}).get("question", "")
                self.audit_log.record(
                    agent_id="front_agent",
                    action="route",
                    model_id=self.model,
                    detail={
                        "decision": "llm_dynamic_routing",
                        "tool_name": tool_use.name,
                        "domain": domain,
                        "question": question,
                    },
                )
                result_text = self._consult_specialist(domain, question)
                tool_result_blocks.append(
                    {"type": "tool_result", "tool_use_id": tool_use.id, "content": result_text}
                )

            self.messages.append({"role": "user", "content": tool_result_blocks})

        return "申し訳ございません、只今混み合っております。担当の行員におつなぎします。"

    def _consult_specialist(self, domain: str | None, question: str) -> str:
        return consult_specialist(domain, question, self.audit_log, model_id=self.model)
