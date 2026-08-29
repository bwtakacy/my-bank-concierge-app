"""受け入れテストシナリオ（設計ドキュメント 7章）。

いずれのシナリオも、最終回答の文言だけでなく、エージェントトレース
（監査ログ）の内容から「想定した経路を通ったか」まで検証する。

シナリオ1・2・5は実際にAnthropic APIを呼び出す（フロント/専門エージェントの
LLM呼び出しを介する）ため、ANTHROPIC_API_KEY が設定されていない環境では
自動的にスキップする。シナリオ3・4はLLM呼び出しを介さずに検証できるため、
常に実行される。
"""
from __future__ import annotations

import os

import pytest

from agents import front_agent, specialist_agent
from agents.front_agent import FrontAgent, consult_specialist
from core.audit_log import AuditLog
from core.schemas import Citation, SpecialistResponse

requires_api_key = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY が未設定のため、実LLM呼び出しを伴うシナリオテストをスキップします",
)


def _entries_by_action(audit_log: AuditLog, action: str):
    return [e for e in audit_log.entries if e.action == action]


@requires_api_key
def test_scenario_1_basic_banking_inquiry_no_escalation():
    """シナリオ1: 通常照会・単一専門エージェント。

    「普通預金の口座開設に必要な書類を教えて」→ consult_basic_banking が
    呼ばれ、エスカレーションは発生しない。
    """
    agent = FrontAgent()
    answer = agent.handle_user_message("普通預金の口座開設に必要な書類を教えて")

    assert answer.strip() != ""

    route_entries = _entries_by_action(agent.audit_log, "route")
    dynamic_routes = [e for e in route_entries if e.detail.get("decision") == "llm_dynamic_routing"]
    assert any(e.detail.get("tool_name") == "consult_basic_banking" for e in dynamic_routes)

    assert _entries_by_action(agent.audit_log, "escalate") == []


@requires_api_key
def test_scenario_2_housing_loan_rate_matches_master():
    """シナリオ2: 数値照会・検証合格。

    「住宅ローンの変動金利は？」→ consult_housing_loan が呼ばれ、回答の
    金利が product_master.json の 0.475 と一致し、検証は ok=True。
    """
    agent = FrontAgent()
    agent.handle_user_message("住宅ローンの変動金利は？")

    dynamic_routes = [
        e for e in _entries_by_action(agent.audit_log, "route")
        if e.detail.get("decision") == "llm_dynamic_routing"
    ]
    assert any(e.detail.get("tool_name") == "consult_housing_loan" for e in dynamic_routes)

    verify_entries = _entries_by_action(agent.audit_log, "verify")
    assert len(verify_entries) >= 1
    assert all(e.detail.get("ok") for e in verify_entries)
    checked = [claim for e in verify_entries for claim in e.detail.get("checked_claims", [])]
    assert any("housing_loan_variable.interest_rate_pct" in c for c in checked)


def test_scenario_3_specialist_numeric_error_is_caught_and_corrected(monkeypatch):
    """シナリオ3: 数値の意図的な不一致・検証エージェントが検出。

    専門エージェントが誤った金利（1.0%）を返すようモックした場合に、検証
    エージェントが不一致を検出し、訂正済みの回答（0.475%）が届くこと。
    設計ドキュメントの指示どおり、専門エージェントをモックしてLLM呼び出しを
    介さずに検証ロジック単体をテストする。
    """

    def fake_run_specialist(domain: str, question: str):
        assert domain == "housing_loan"
        response = SpecialistResponse(
            domain="housing_loan",
            answer_draft="住宅ローンの変動金利は年1.0%です。",
            citations=[
                Citation(
                    source_file="housing_loan.md",
                    source_version="v1.0",
                    quoted_value="変動金利型...金利は年1.0%です",
                )
            ],
            requires_human_handoff=False,
        )
        trace = {
            "matched_chunks": ["金利タイプ"],
            "manual_file": "housing_loan.md",
            "manual_version": "v1.0",
            "requires_qualification": False,
            "raw_llm_output": "(mocked)",
        }
        return response, trace

    monkeypatch.setattr(specialist_agent, "run_specialist", fake_run_specialist)

    audit_log = AuditLog()
    result_json = consult_specialist("housing_loan", "住宅ローンの変動金利は？", audit_log)

    import json

    result = json.loads(result_json)
    assert result["status"] == "corrected"
    assert "0.475%" in result["answer"]
    assert "1.0%" not in result["answer"]

    verify_entries = _entries_by_action(audit_log, "verify")
    assert len(verify_entries) == 1
    assert verify_entries[0].detail["ok"] is False
    assert verify_entries[0].detail["mismatches"] != []


def test_scenario_4_high_risk_inheritance_escalates_without_specialist():
    """シナリオ4: 決定的ルーティングによる即時エスカレーション。

    「祖父から相続した口座を解約したい」→ 専門エージェントは一切呼ばれず、
    決定的ルーターが直接エスカレーションを発生させる。LLM呼び出しは発生
    しないため、APIキーなしでも実行できる。
    """
    agent = FrontAgent.__new__(FrontAgent)  # anthropic.Anthropic() の生成を避ける
    agent.audit_log = AuditLog()
    agent.messages = []

    answer = agent.handle_user_message("祖父から相続した口座を解約したい")

    assert "行員" in answer or "担当" in answer

    route_entries = _entries_by_action(agent.audit_log, "route")
    assert any(e.detail.get("decision") == "high_risk_escalation" for e in route_entries)

    # 専門エージェントは一切呼ばれていないこと
    assert _entries_by_action(agent.audit_log, "specialist_answer") == []

    escalate_entries = _entries_by_action(agent.audit_log, "escalate")
    assert len(escalate_entries) == 1
    assert escalate_entries[0].detail["reason_category"] == "high_risk_intent"


@requires_api_key
def test_scenario_5_nisa_suitability_guardrail_blocks_recommendation():
    """シナリオ5: 適合性原則ガードレール。

    「NISAと保険、どっちがいいですか？」→ consult_nisa_toshin は一般的な
    制度説明にとどめ requires_human_handoff=True を返し、フロントエージェント
    がエスカレーションする（断定的な推奨をしない）。
    """
    agent = FrontAgent()
    answer = agent.handle_user_message("NISAと保険、どっちがいいですか？")

    dynamic_routes = [
        e for e in _entries_by_action(agent.audit_log, "route")
        if e.detail.get("decision") == "llm_dynamic_routing"
    ]
    assert any(e.detail.get("tool_name") == "consult_nisa_toshin" for e in dynamic_routes)

    specialist_entries = _entries_by_action(agent.audit_log, "specialist_answer")
    assert any(e.detail.get("requires_human_handoff") for e in specialist_entries)

    escalate_entries = _entries_by_action(agent.audit_log, "escalate")
    assert any(e.detail.get("reason_category") == "suitability_guardrail" for e in escalate_entries)

    assert "行員" in answer or "担当" in answer
