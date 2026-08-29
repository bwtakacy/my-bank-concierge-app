from agents.verify_agent import verify
from core.schemas import Citation, SpecialistResponse


def test_matching_variable_rate_passes():
    response = SpecialistResponse(
        domain="housing_loan",
        answer_draft="住宅ローンの変動金利は年0.475%です。",
        citations=[
            Citation(
                source_file="housing_loan.md",
                source_version="v1.0",
                quoted_value="変動金利型...金利は年0.475%です",
            )
        ],
    )
    result = verify(response)
    assert result.ok is True
    assert result.mismatches == []
    assert len(result.checked_claims) == 1


def test_mismatched_variable_rate_is_detected_and_corrected():
    # 専門エージェントが誤った金利（1.0%）を返したケースをシミュレートする
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
    )
    result = verify(response)
    assert result.ok is False
    assert len(result.mismatches) == 1
    assert result.corrected_answer is not None
    assert "0.475%" in result.corrected_answer
    assert "1.0%" not in result.corrected_answer


def test_fixed_rate_mismatch_uses_correct_master_value():
    response = SpecialistResponse(
        domain="housing_loan",
        answer_draft="住宅ローン（10年固定）の金利は年2.0%です。",
        citations=[
            Citation(
                source_file="housing_loan.md",
                source_version="v1.0",
                quoted_value="固定金利型（10年固定）...金利は年2.0%です",
            )
        ],
    )
    result = verify(response)
    assert result.ok is False
    assert "1.35%" in result.corrected_answer


def test_no_numeric_claims_passes_trivially():
    # NISAの一般的な制度説明のみで、数値主張が無いケース
    response = SpecialistResponse(
        domain="nisa_toshin",
        answer_draft="NISAには、つみたて投資枠と成長投資枠があります。",
        citations=[
            Citation(
                source_file="nisa_toshin.md",
                source_version="v1.0",
                quoted_value="NISA制度には、つみたて投資枠と成長投資枠があります",
            )
        ],
        requires_human_handoff=True,
        handoff_reason="適合性原則の対象領域のため断定的な推奨を避ける",
    )
    result = verify(response)
    assert result.ok is True
    assert result.checked_claims == []


def test_furikomi_fee_matches_master():
    response = SpecialistResponse(
        domain="basic_banking",
        answer_draft="他行宛のATM振込手数料は220円です。",
        citations=[
            Citation(
                source_file="basic_banking.md",
                source_version="v1.0",
                quoted_value="他行宛の振込手数料は220円です",
            )
        ],
    )
    result = verify(response)
    assert result.ok is True
