"""T36 ②-b 결합 갈래 — 사슬 화합물 결합선(과학 점자 제10항, 재추출 4506행~).

결합선과 원소 기호는 붙여 적고 결합선은 ; 뒤에 단일 1 · 이중 2 · 삼중 3. 식 전체가 원소 기호와 결합선으로만
된 경우만 결합선으로 읽는다(수식의 `=`·`-` 를 건드리지 않는다).
"""
import pytest

from app.ai.braille.kor_math_rules import bond_chain, convert_latex
from app.ai.braille.translator import translate_body


@pytest.mark.parametrize("src, want", [
    ("H-O-H", "⠠⠠⠠⠓⠰⠂⠕⠰⠂⠓⠠⠄"),                  # 4511행 ,,,h;1o;1h,'
    ("O=C=O", "⠠⠠⠠⠕⠰⠆⠉⠰⠆⠕⠠⠄"),                  # 4513행 ,,,o;2c;2o,'
    ("H-C≡C-H", "⠠⠠⠠⠓⠰⠂⠉⠰⠒⠉⠰⠂⠓⠠⠄"),            # 4515행 ,,,h;1c;3c;1h,'
])
def test_결합선(src, want):
    assert translate_body(src)[0][0] == want


def test_수식은_결합선이_아니다():
    for s in ("V=IR", "A-B", "x=1", "a-b=c"):
        assert bond_chain(s) is None, s
    assert convert_latex("A-B") == "⠠⠁⠔⠠⠃"
