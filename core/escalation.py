"""人間エスカレーションのスタブ（設計ドキュメント 4.1 / 4.4 節）。

実運用システムでは、ここで有人チャット・呼び出しキュー等の実システムに
接続することになるが、本デモではそのスタブとして「エスカレーション事由を
記録し、顧客向けの定型メッセージを返す」だけの実装とする。

このモジュールを呼ぶこと自体が「実行境界（AIがここから先は処理しない）」
を明示するポイントであるため、フロントエージェントは専門エージェントの
判断結果に関わらず、以下の入口からのみエスカレーションを発生させる。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EscalationResult:
    reason_category: str
    reason_detail: str
    customer_message: str


DEFAULT_CUSTOMER_MESSAGE = (
    "こちらの件につきましては、担当の行員におつなぎいたします。"
    "恐れ入りますが、窓口担当者よりあらためてご案内させていただきます。"
)


def escalate(reason_category: str, reason_detail: str) -> EscalationResult:
    """人間エスカレーションを発生させる（スタブ）。

    reason_category: "high_risk_intent"（決定的ルーター経由）や
        "suitability_guardrail"（適合性原則ガードレール）、
        "verification_unresolved"（検証エージェントが訂正不能な不一致を検出）
        など、発生源を識別する短い文字列。
    reason_detail: 人間の担当者向けの詳細メモ。
    """
    return EscalationResult(
        reason_category=reason_category,
        reason_detail=reason_detail,
        customer_message=DEFAULT_CUSTOMER_MESSAGE,
    )
