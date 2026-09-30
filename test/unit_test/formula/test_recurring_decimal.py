r"""순환소수·소수점 — 수학 점자 제8항.

1호 소수점은 ⠲. 정수부가 없으면 **수표 뒤 바로 소수점**이다(`.47` = `#4dg`).
2호 순환마디는 그 **앞에 ⠈ 를 한 번만** 적는다. 마디가 둘로 떨어져 있어도 여는 자리에만.

종전에는 결합 점(U+0307)도 `\dot{}` 명령도 몰라 미지문자로 샜다 — 규정 예시 6건이
전부 틀렸다.
"""
import pytest

from app.ai.braille.kor_math_rules import convert_latex
from app.utils.braille_ascii import unicode_to_ascii


def _brf(t: str) -> str:
    return unicode_to_ascii(convert_latex(t)).replace("`", "").strip()


@pytest.mark.parametrize("src,want", [
    ("0.17", "#j4ag"),          # 1호
    ("0.6̇", "#j4@f"),     # 2호 — 결합 점
    ("0.73̇9̇", "#j4g@ci"),
    ("0.1̇234"[:4] + "̇" + "23̇", "#j4@abc"),
])
def test_규정_예시(src, want):
    assert _brf(src) == want


@pytest.mark.parametrize("src,want", [
    (r"0.\dot{6}", "#j4@f"),
    (r"0.7\dot{3}\dot{9}", "#j4g@ci"),
    (r"0.\dot{1}2\dot{3}", "#j4@abc"),
    (r".\dot{9}", "#4@i"),
])
def test_dot_명령도_같다(src, want):
    assert _brf(src) == want


@pytest.mark.parametrize("src,want", [("0.5", "#j4e"), ("3.14", "#c4ad")])
def test_평범한_소수는_그대로(src, want):
    assert _brf(src) == want


# 숫자 셀은 연속 범위가 아니다(7=⠛ U+281B 가 ⠁-⠚ 밖). 범위식으로 찾던 자리에서
# 7 이 든 수만 틀렸다(#1048). 기대값은 위 규정 예시(재추출 3176~3179행)와 같은 규칙.
@pytest.mark.parametrize("src,want", [
    (".47", "#4dg"),                    # 1호 규정 예시
    (".75", "#4ge"),                    # 수표 겹침 걷기 — 종전 #4#ge
    (r"0.\dot{7}\dot{4}", "#j4@gd"),     # 2호 — 종전 #j4g@d
    (r"0.1\dot{7}", "#j4a@g"),           # 종전 #j4ag@
])
def test_숫자7_든_소수(src, want):
    assert _brf(src) == want


def test_앱_소스에_숫자_범위식이_없다():
    """`[⠁-⠚]` 는 7 을 빼고 ⠂⠄⠈⠕ 같은 비숫자를 넣는다. 숫자 셀은 열 개를 적는다."""
    import re
    from pathlib import Path
    app = Path(__file__).resolve().parents[3] / "app"
    assert (app / "ai" / "braille").is_dir()   # 경로가 틀리면 빈 목록으로 공짜 통과한다
    bad = [f"{p.relative_to(app)}:{i}" for p in app.rglob("*.py")
           for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if re.search(r"⠁-⠚", line.split("#", 1)[0])]
    assert not bad, bad
