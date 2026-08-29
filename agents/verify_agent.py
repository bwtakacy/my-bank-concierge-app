"""検証エージェント（設計ドキュメント 4.4 節）。

設計方針上は「検証専用サブエージェント」だが、本デモではLLMを使わない
ルールベース実装とする。数値照合はLLMに頼らず機械的に行う方が確実であり、
かつ「検証はAIの判断ではなく構造的なチェックである」ことを可視化できる
ため（金利・手数料等の数値は要約させず原典引用+出典表示を必須化し、
検証エージェントで原文一致を機械照合する、という設計方針の直接的な実装）。
"""
from __future__ import annotations

import re

from core.schemas import SpecialistResponse, VerificationResult
from tools import master_lookup

# (domain, 必須キーワード群, product_id, field_name, 値の種類)
# 必須キーワードが quoted_value にすべて含まれていれば、その citation は
# この product_id.field_name に対する数値主張とみなす。
_KeywordRule = tuple[str, tuple[str, ...], str, str, str]

_RULES: list[_KeywordRule] = [
    ("housing_loan", ("変動", "金利"), "housing_loan_variable", "interest_rate_pct", "percent"),
    ("housing_loan", ("固定", "金利"), "housing_loan_fixed_10y", "interest_rate_pct", "percent"),
    ("housing_loan", ("変動", "手数料"), "housing_loan_variable", "arrangement_fee_jpy", "yen"),
    ("housing_loan", ("固定", "手数料"), "housing_loan_fixed_10y", "arrangement_fee_jpy", "yen"),
    ("housing_loan", ("事務手数料",), "housing_loan_variable", "arrangement_fee_jpy", "yen"),
    ("basic_banking", ("振込", "手数料"), "furikomi_atm", "fee_jpy", "yen"),
    ("nisa_toshin", ("つみたて", "上限"), "nisa_tsumitate", "annual_limit_jpy", "yen"),
    ("nisa_toshin", ("年間", "投資枠"), "nisa_tsumitate", "annual_limit_jpy", "yen"),
]

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_YEN_RE = re.compile(r"([\d,]+(?:\.\d+)?)\s*円")


def _find_rule(domain: str, text: str) -> _KeywordRule | None:
    for rule in _RULES:
        rule_domain, keywords, *_rest = rule
        if rule_domain != domain:
            continue
        if all(kw in text for kw in keywords):
            return rule
    return None


def _extract_number(text: str, value_kind: str) -> tuple[str, float] | None:
    """text から数値を抽出する。 (原文中のマッチ文字列, 数値) を返す。"""
    if value_kind == "percent":
        m = _PERCENT_RE.search(text)
        if not m:
            return None
        return m.group(0), float(m.group(1))
    if value_kind == "yen":
        m = _YEN_RE.search(text)
        if not m:
            return None
        return m.group(0), float(m.group(1).replace(",", ""))
    return None


def _format_value(value: float, value_kind: str) -> str:
    if value_kind == "percent":
        # 0.475 のような値も、末尾の不要な0を削らずそのまま表示する
        text = f"{value:g}"
        return f"{text}%"
    if value_kind == "yen":
        return f"{value:,.0f}円"
    return str(value)


def verify(response: SpecialistResponse) -> VerificationResult:
    """response.citations に含まれる数値主張を product_master.json と突き合わせる。

    - citations に数値主張が無い（一般的な制度説明のみ）場合は ok=True。
    - 一致すれば ok=True。
    - 不一致なら mismatches に詳細を積み、master側の正しい値で
      corrected_answer を組み立てる（answer_draft 中の誤った数値表記を
      正しい表記に置換する）。
    """
    checked_claims: list[str] = []
    mismatches: list[str] = []
    corrected_answer = response.answer_draft

    any_mismatch = False

    for citation in response.citations:
        rule = _find_rule(response.domain, citation.quoted_value)
        if rule is None:
            # このcitationは既知の商品マスタ項目に対応付けられなかった。
            # （一般的な説明文、または本デモの照合ルールが未対応のケース）
            continue

        _, _keywords, product_id, field_name, value_kind = rule
        extracted = _extract_number(citation.quoted_value, value_kind)
        if extracted is None:
            continue

        matched_text, quoted_number = extracted
        master_product = master_lookup.get_product(product_id)
        if master_product is None or field_name not in master_product:
            continue
        master_value = float(master_product[field_name])

        claim_desc = (
            f"{product_id}.{field_name}: 引用値={_format_value(quoted_number, value_kind)} "
            f"/ マスタ値={_format_value(master_value, value_kind)}"
        )
        checked_claims.append(claim_desc)

        if abs(quoted_number - master_value) > 1e-9:
            any_mismatch = True
            correct_text = _format_value(master_value, value_kind)
            mismatches.append(
                f"{product_id}.{field_name} が不一致: 回答は「{matched_text}」でしたが、"
                f"商品マスタ（{master_lookup.get_master_version()}）の正しい値は「{correct_text}」です。"
            )
            # answer_draft 中の誤表記を正しい表記に置換する
            corrected_answer = corrected_answer.replace(matched_text, correct_text)

    if not any_mismatch:
        return VerificationResult(ok=True, checked_claims=checked_claims, mismatches=[], corrected_answer=None)

    return VerificationResult(
        ok=False,
        checked_claims=checked_claims,
        mismatches=mismatches,
        corrected_answer=corrected_answer,
    )
