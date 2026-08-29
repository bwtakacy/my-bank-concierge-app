"""Anthropicクライアント生成の共通ヘルパー。

identity-linked API key（Anthropic Consoleでユーザーに紐づけて発行したキー）を
使う場合、リクエストがどのワークスペースの権限で動くかを
`anthropic-workspace-id` ヘッダーで明示する必要がある。ANTHROPIC_WORKSPACE_ID
が設定されていればヘッダーに付与し、未設定なら通常キー向けに何も付けない。
"""
from __future__ import annotations

import os

import anthropic


def get_client() -> anthropic.Anthropic:
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID")
    if workspace_id:
        return anthropic.Anthropic(
            default_headers={"anthropic-workspace-id": workspace_id}
        )
    return anthropic.Anthropic()
