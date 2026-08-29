"""監査ログ（設計ドキュメント 4.5 節）。

各ターンで発生した route / specialist_answer / verify / escalate の
イベントを、タイムスタンプ・エージェントID・モデルID・参照マニュアル版と
ともに記録する。永続化はデモ用途のためメモリ上のリストで十分だが、
JSON Lines形式で追記できる補助関数も用意しておく。

Streamlit UI のサイドバー（エージェントトレースパネル）は、この
AuditLog をそのまま表示に使う。マルチエージェントが実際にどう連携して
いるかを見せる、このデモの価値の中心となるコンポーネント。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from core.schemas import AuditLogEntry

DEFAULT_LOG_PATH = Path(__file__).resolve().parent.parent / "audit_log.jsonl"


class AuditLog:
    """1回の会話ターン（またはセッション全体）分のイベントを保持する。"""

    def __init__(self) -> None:
        self._entries: list[AuditLogEntry] = []

    def record(
        self,
        *,
        agent_id: str,
        action: str,
        detail: dict | None = None,
        model_id: str | None = None,
        manual_version: str | None = None,
    ) -> AuditLogEntry:
        entry = AuditLogEntry(
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            agent_id=agent_id,
            model_id=model_id,
            manual_version=manual_version,
            action=action,  # type: ignore[arg-type]
            detail=detail or {},
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[AuditLogEntry]:
        return list(self._entries)

    def clear(self) -> None:
        self._entries.clear()

    def append_to_file(self, path: Path = DEFAULT_LOG_PATH) -> None:
        """デモ用の簡易永続化。JSON Linesで追記する。"""
        with path.open("a", encoding="utf-8") as f:
            for entry in self._entries:
                f.write(
                    json.dumps(
                        {
                            "timestamp": entry.timestamp,
                            "agent_id": entry.agent_id,
                            "model_id": entry.model_id,
                            "manual_version": entry.manual_version,
                            "action": entry.action,
                            "detail": entry.detail,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
