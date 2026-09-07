"""「과학 점자」 제4·5항 대문자 구절표.

규정 원문 `braille-source/text/한국 점자 규정_재추출.txt`
  4363행 제4항  "로마자 하나로 된 원소 기호가 3개 이상 이어 나올 때에는 대문자 구절표…"
  4367-4368행   CH₃COOH → `0,,,ch;#c"cooh,'4`
  4417-4418행 제5항 "…H, B, C, F, I의 원소 기호가 숫자 다음에 붙어 나올 때…앞에 `"`을 적는다"

방아쇠가 넓어지면 본문이 깨진다(코퍼스 실측: 조건만 쓰면 91회 중 88회 오발동).
그래서 **오발동 쪽도 같이 잠근다.**
"""
from app.ai.braille.kor_math_rules import caps_phrase_run
from app.ai.braille.translator import translate_plain


def test_reg_example_cell_exact():
    """규정 4367-4368행과 셀 단위로 같아야 한다."""
    got = translate_plain("아세트산의 화학식은 CH₃COOH이다.")
    assert "⠴⠠⠠⠠⠉⠓⠰⠼⠉⠐⠉⠕⠕⠓⠠⠄⠲" in got, got


def test_math_path_same():
    assert translate_plain("$\\mathrm{CH_3COOH}$").strip() == "⠴⠠⠠⠠⠉⠓⠰⠼⠉⠐⠉⠕⠕⠓⠠⠄⠲"


def test_trigger_true():
    for s in ("CH₃COOH", "$\\mathrm{HCO_3^-}$", "$\\mathrm{H_2SO_4}$"):
        assert caps_phrase_run(s), s


def test_trigger_false():
    # 원소 기호 3연이지만 화학식이 아닌 것 — 코퍼스에서 실제로 나온 것들
    for s in ("SNS", "WHO", "HIV", "MOUNTAIN", "COFFEE", "HCN",
              "$X^{A}YBB$", "$\\angle PBC$", "H₂O", "CO₂"):
        assert not caps_phrase_run(s), s


def test_no_regression_on_hangul_sentence():
    got = translate_plain("다음 보기에서 SNS와 HIV")
    assert "⠠⠠⠠" not in got, got
