"""수식 응답의 `$` 짝 (2026-09-10).

`_extract` 의 옛 `_DOLLAR_RE` 는 앞뒤 `$` 를 **따로** 지워, 문장이 섞인 요소에서
앞 하나만 벗겨 짝을 깼다. 고급 점역 이식 뒤 LLM 판독 512건 중 **100건(19.5%)** 이
이 꼴이었다. 점자는 안 바뀌지만(`convert_latex` 가 `$` 를 어차피 지운다) 점역사
편집창에 짝 안 맞는 `$` 가 그대로 보인다.

벗기는 일은 `_normalize` 의 `_BLOCK_WRAP_RE`(양끝이 같은 구분자일 때만) 가 맡는다.
호출부가 `_normalize(_extract(...) or raw)` 라 `$$…$$` 는 여전히 지워진다.
"""
from app.ai.llm.formula_opt import _extract, _normalize


def _pipe(s: str) -> str:
    """운영 호출부와 같은 순서 — formula_opt.py `_normalize(_extract(...) or raw)`."""
    return _normalize(_extract(s) or s)


def test_문장_섞인_요소의_달러_짝이_안_깨진다():
    s = r"$f(x) \ge kx$이므로 곡선 $y=f(x)$와 직선 $y=kx$가 접하거나 만나지 않는다."
    out = _pipe(s)
    assert out.count("$") % 2 == 0
    assert out.startswith("$f(x)")


def test_블록_구분자는_여전히_벗겨진다():
    assert _pipe("$$\n\\frac{1}{2}\n$$") == "\\frac{1}{2}"
    assert _pipe("$x=1$") == "x=1"


def test_코드펜스는_여전히_벗겨진다():
    assert _pipe("```latex\n\\frac{a}{b}\n```") == "\\frac{a}{b}"
