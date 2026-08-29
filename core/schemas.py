"""内部データモデル定義。

設計ドキュメント 3.3 節に対応する。ここで定義する型は、専門エージェント・
検証エージェント・フロントエージェント・監査ログの間でやり取りされる
構造化データの「契約」として機能する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Citation:
    """専門エージェントの回答に付随する出典情報。

    数値主張には必ずこれを付け、原文からそのまま引用した文字列を
    quoted_value に保持する（要約・言い換えをしない）。検証エージェントは
    この quoted_value から数値を抽出し、商品マスタと突き合わせる。
    """

    source_file: str
    source_version: str
    quoted_value: str


@dataclass
class SpecialistResponse:
    """専門エージェント（Scout-then-act の Act 段階）の出力。"""

    domain: str
    answer_draft: str
    citations: list[Citation] = field(default_factory=list)
    requires_human_handoff: bool = False
    handoff_reason: str | None = None


@dataclass
class VerificationResult:
    """検証エージェントの出力。"""

    ok: bool
    checked_claims: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    corrected_answer: str | None = None


@dataclass
class AuditLogEntry:
    """監査ログ1件分。エージェントトレースパネルの表示元データ。"""

    timestamp: str
    agent_id: str
    model_id: str | None
    manual_version: str | None
    action: Literal["route", "specialist_answer", "verify", "escalate"]
    detail: dict = field(default_factory=dict)
