"""高リスク意図の決定的ルーティング（設計ドキュメント 4.1 節）。

LLMによる動的ルーティングの「前段」で必ず呼ばれる。正規表現/キーワードに
ヒットした場合は、専門エージェントを一切呼ばずに人間エスカレーションへ
直行させる。実行境界（AIがどこまで処理してよいか）を、LLMの判断に委ねず
コードで固定していることが設計上のポイントであり、テスト容易性・
説明責任の観点からも重要。
"""
from __future__ import annotations

HIGH_RISK_PATTERNS: dict[str, list[str]] = {
    "相続": ["相続", "遺言", "死亡", "亡くなった"],
    "解約": ["解約したい", "口座を閉じ", "口座を解約"],
    "クレーム": ["苦情", "クレーム", "納得できない", "訴える"],
}


def check_high_risk(user_message: str) -> str | None:
    """ヒットした場合はカテゴリ名（HIGH_RISK_PATTERNS のキー）を返す。

    ヒットしなければ None を返す。
    """
    for category, keywords in HIGH_RISK_PATTERNS.items():
        for keyword in keywords:
            if keyword in user_message:
                return category
    return None


def matched_keyword(user_message: str) -> tuple[str, str] | None:
    """デバッグ・トレース表示用: ヒットしたカテゴリと実際のキーワードを返す。"""
    for category, keywords in HIGH_RISK_PATTERNS.items():
        for keyword in keywords:
            if keyword in user_message:
                return category, keyword
    return None
