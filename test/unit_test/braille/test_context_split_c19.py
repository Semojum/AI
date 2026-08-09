"""문맥에 따라 점형이 갈리는 묵자 4자 (원장 C-19).

같은 글자가 조항 둘에 걸쳐 있어 표 조회 하나로는 못 낸다. 분기점은 두 곳뿐이다.
  · 수식/텍스트 — `_translate_with_braillify`가 `_FORMULA_RE`로 세그먼트를 가른다
    (수식은 convert_latex, 텍스트는 substitute_symbols).
  · 따옴표 짝 — `_normalize_apostrophe`(요소 전체에서 ‘…’ 짝을 센다).

    ′  수학 제17항 프라임 ⠤        ↔ 제69항 단위 분·피트 ⠴⠤
    ·  제49항 가운뎃점 ⠐⠆          ↔ 수학 제2항[붙임] 곱셈 ⠐
    ’  제49항 닫는 작은따옴표 ⠴⠄   ↔ 제61항 아포스트로피 ⠄
    ×  수학 제2항 곱셈표 ⠡         ↔ 제57항 숨김표 ⠸⠭ⁿ⠇ (2개 이상 연속일 때만)

×··는 이미 갈려 있었고 이 파일이 그 상태를 못 박는다 — 특히 ×는 symbol_table의
**카테고리 순서**(수학연산이 문장부호보다 뒤)에 기대고 있어 JSON을 재배열하면 조용히
숨김표로 뒤집힌다.
"""
from app.ai.braille.translator import translate_tagged_text, translate_with_breaks


def _line(text: str) -> str:
    return translate_with_breaks(text)[0][0]


# ── ′ 제17항(수식) ↔ 제69항(단위) ──────────────────────────────────────────
def test_prime_in_formula_is_hyphen_cell():
    """f′(x)는 수식 세그먼트로 가서 제17항 ⠤."""
    assert "⠋⠤⠦⠭⠴" in translate_tagged_text("f′(x)를 구하여라.")
    assert "⠋⠤⠦⠭⠴" in translate_tagged_text("$f'(x)=2x$")


def test_prime_after_digit_is_unit_minute():
    """숫자 뒤 ′″는 제69항 분·초 ⠴⠤ / ⠴⠤⠤ (도 ⠴⠙와 같은 계열)."""
    out = translate_tagged_text("각도는 30° 15′ 20″이다.")
    assert "⠴⠙" in out          # 30°
    assert "⠼⠁⠑⠴⠤" in out      # 15′
    assert "⠼⠃⠚⠴⠤⠤" in out     # 20″


# ── · 제49항(가운뎃점) ↔ 수학 제2항[붙임](곱셈) ───────────────────────────
def test_middot_in_text_is_reg49():
    assert "⠐⠆" in translate_tagged_text("가·나·다 순으로 적는다.")
    # 제50항 [붙임] — 숫자 사이 가운뎃점도 문장부호다(뒤 숫자에 수표 재삽입)
    assert "⠼⠉⠐⠆⠼⠁" in translate_tagged_text("3·1 운동이 일어났다.")


def test_middot_in_formula_is_multiplication():
    assert translate_tagged_text("$a·b=6$").startswith("⠁⠐⠃")


# ── ’ 제49항(닫는 따옴표) ↔ 제61항(아포스트로피) ─────────────────────────
def test_apostrophe_in_english_is_one_cell():
    """짝 없는 ’ + 로마자 인접 = 제61항 ⠄. gold 외국어 p011 `HASN'T` 대조."""
    assert "⠓⠁⠎⠝⠄⠞" in _line("it hasn’t been worn in years")
    assert "⠄⠎" in _line("Let’s say an ant")
    assert "⠍⠕⠝⠅⠑⠽⠎⠄" in _line("monkeys’ learned behavior")


def test_closing_quote_stays_two_cells():
    """짝이 맞으면 안이 로마자여도 제49항 ⠴⠄ — ‘cultus’·‘S’를 아포스트로피로 보면 안 된다."""
    assert "⠴⠄" in _line("라틴어 ‘cultus’에서 유래한")
    assert "⠴⠄" in _line("집합 ‘S’를, 오른쪽의 원은")
    assert "⠴⠄" in _line("밑줄 친 ‘이것’에 부합하는")


def test_unmatched_quote_without_roman_stays_quote():
    """여는 ‘를 추출이 흘려도 로마자가 안 붙었으면 닫는 따옴표로 둔다(사회문화 p062 형)."""
    assert _line("당’, ‘캠핑당’등 다양한 종류").startswith("⠊⠶⠴⠄")


# ── × 수학 제2항(곱셈) ↔ 제57항(숨김표) ───────────────────────────────────
def test_single_x_is_multiplication():
    """단독 ×는 곱셈 ⠡ — symbol_table 카테고리 순서(수학연산이 뒤)에 기댄 값이다."""
    assert "⠡" in translate_tagged_text("2×3=6")
    assert "⠡" in translate_tagged_text("가로×세로")


def test_repeated_x_is_hidden_mark():
    """제57항 원문 예시: 이 ×××야! = `o`_xxxl>6`."""
    assert "⠸⠭⠭⠭⠇" in translate_tagged_text("이 ×××야!")
