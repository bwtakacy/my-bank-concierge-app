"""銀行窓口コンシェルジュAIエージェント デモアプリ（Streamlitエントリポイント）。

設計ドキュメント 6章の要件どおり、メインパネルにチャットUI、サイドバーに
エージェントトレースパネル（フロント/専門/検証の各エージェントが実際に
どう連携しているかを見せる）を持つ2ペイン構成とする。
"""
from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from agents.front_agent import FrontAgent
from core.audit_log import AuditLog

load_dotenv()

st.set_page_config(page_title="銀行窓口コンシェルジュ AI デモ", layout="wide")

ACTION_LABELS = {
    "route": "🧭 ルーティング",
    "specialist_answer": "🗂️ 専門エージェント回答",
    "verify": "🔍 検証エージェント",
    "escalate": "🙋 人間エスカレーション",
}


def _init_state() -> None:
    if "audit_log" not in st.session_state:
        st.session_state.audit_log = AuditLog()
    if "front_agent" not in st.session_state:
        st.session_state.front_agent = FrontAgent(audit_log=st.session_state.audit_log)
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # [{"role": "user"|"assistant", "content": str}]
    if "turns" not in st.session_state:
        st.session_state.turns = []  # [{"user_message": str, "entries": [AuditLogEntry, ...]}]


def _render_route_entry(detail: dict) -> None:
    decision = detail.get("decision")
    if decision == "high_risk_escalation":
        st.error(f"決定的ルーター（正規表現）が高リスク意図を検出: **{detail.get('category')}**\n\n"
                  f"→ 専門エージェントを呼ばずに即座にエスカレーション")
    elif decision == "no_high_risk_hit":
        st.caption("決定的ルーター: 高リスク意図なし → LLM動的ルーティングへ")
    elif decision == "llm_dynamic_routing":
        st.info(
            f"LLM動的ルーティング（tool use）: `{detail.get('tool_name')}` を呼び出し "
            f"（ドメイン: `{detail.get('domain')}`）\n\n質問要約: {detail.get('question')}"
        )


def _render_specialist_entry(entry) -> None:
    detail = entry.detail
    st.markdown(f"**ドメイン**: `{entry.agent_id}` ／ **参照マニュアル**: "
                f"`{detail.get('manual_file')}` (version: `{entry.manual_version}`)")
    if detail.get("matched_chunks"):
        st.caption("Scout段階でヒットした見出し: " + " / ".join(detail["matched_chunks"]))
    else:
        st.caption("Scout段階: マニュアル抜粋がヒットしませんでした")
    st.markdown("回答ドラフト（顧客への最終回答に整形される前の生データ）:")
    st.markdown(f"> {detail.get('answer_draft')}")
    citations = detail.get("citations") or []
    if citations:
        st.markdown("出典:")
        for c in citations:
            st.caption(f"- {c.get('source_file')} ({c.get('source_version')}): 「{c.get('quoted_value')}」")
    if detail.get("requires_human_handoff"):
        st.warning(f"requires_human_handoff = True: {detail.get('handoff_reason')}")


def _render_verify_entry(detail: dict) -> None:
    if detail.get("ok"):
        st.success("検証OK（数値主張は商品マスタと一致、またはチェック対象なし）")
    else:
        st.error("検証NG: 数値の不一致を検出")
        for m in detail.get("mismatches", []):
            st.markdown(f"- {m}")
        if detail.get("corrected_answer"):
            st.markdown("**訂正済み回答**:")
            st.markdown(f"> {detail['corrected_answer']}")
    if detail.get("checked_claims"):
        with st.expander("照合した数値主張の詳細", expanded=False):
            for claim in detail["checked_claims"]:
                st.caption(claim)


def _render_escalate_entry(detail: dict) -> None:
    st.warning(f"エスカレーション種別: `{detail.get('reason_category')}`\n\n理由: {detail.get('reason_detail')}")


def _render_turn(turn: dict, expanded: bool) -> None:
    with st.expander(f"🗣️ {turn['user_message'][:40]}", expanded=expanded):
        for entry in turn["entries"]:
            label = ACTION_LABELS.get(entry.action, entry.action)
            st.markdown(f"##### {label}  ·  `{entry.timestamp}`")
            if entry.action == "route":
                _render_route_entry(entry.detail)
            elif entry.action == "specialist_answer":
                _render_specialist_entry(entry)
            elif entry.action == "verify":
                _render_verify_entry(entry.detail)
            elif entry.action == "escalate":
                _render_escalate_entry(entry.detail)
            st.divider()


def main() -> None:
    _init_state()

    st.title("🏦 銀行窓口コンシェルジュ AI デモ")
    st.caption(
        "フロント / 専門 / 検証エージェントの階層型マルチエージェント構成を可視化するデモです。"
        "実在の勘定系・商品データとは接続していません（すべてモックデータです）。"
    )

    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.warning(
            "環境変数 ANTHROPIC_API_KEY が設定されていません。`.env.example` を `.env` に"
            "コピーしてAPIキーを設定してください。",
            icon="⚠️",
        )

    chat_col, trace_col = st.columns([2, 1])

    with trace_col:
        st.subheader("🧵 エージェントトレース")
        st.caption("会話の裏側で各エージェントが何をしたかを、直近のターンから順に表示します。")
        if not st.session_state.turns:
            st.info("まだ会話がありません。左側でメッセージを送信してください。")
        else:
            for i, turn in enumerate(reversed(st.session_state.turns)):
                _render_turn(turn, expanded=(i == 0))

    with chat_col:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        user_input = st.chat_input("お問い合わせ内容を入力してください（例: 住宅ローンの変動金利は？）")
        if user_input:
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with chat_col:
                with st.chat_message("user"):
                    st.markdown(user_input)

            before_count = len(st.session_state.audit_log.entries)
            with chat_col:
                with st.chat_message("assistant"):
                    with st.spinner("🤔 考え中です…（フロント／専門／検証エージェントが連携中）"):
                        answer = st.session_state.front_agent.handle_user_message(user_input)
            after_entries = st.session_state.audit_log.entries[before_count:]

            st.session_state.turns.append({"user_message": user_input, "entries": after_entries})
            st.session_state.chat_history.append({"role": "assistant", "content": answer})

            st.rerun()


if __name__ == "__main__":
    main()
