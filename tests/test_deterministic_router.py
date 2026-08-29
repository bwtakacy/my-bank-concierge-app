from agents.deterministic_router import check_high_risk, matched_keyword


def test_inheritance_is_high_risk():
    assert check_high_risk("祖父から相続した口座を解約したい") is not None


def test_inheritance_category_is_correct_first_match():
    # 「相続」と「解約」の両方にヒットしうる文面。辞書順で最初にヒットした
    # カテゴリが返る仕様を確認する（決定的であること自体が重要）。
    category = check_high_risk("祖父から相続した口座を解約したい")
    assert category in ("相続", "解約")


def test_complaint_is_high_risk():
    assert check_high_risk("この対応には納得できない、クレームです") == "クレーム"


def test_cancel_is_high_risk():
    assert check_high_risk("口座を解約したいのですが") == "解約"


def test_normal_inquiry_is_not_high_risk():
    assert check_high_risk("普通預金の口座開設に必要な書類を教えて") is None


def test_housing_loan_inquiry_is_not_high_risk():
    assert check_high_risk("住宅ローンの変動金利は？") is None


def test_matched_keyword_reports_the_hit():
    result = matched_keyword("亡くなった祖父の口座について相談したい")
    assert result is not None
    category, keyword = result
    assert category == "相続"
    assert keyword in "亡くなった祖父の口座について相談したい"
