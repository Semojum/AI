"""수식 출력에 섞여 나오는 모델 해설문 제거(FE QA — "~방식으로 처리했습니다").

`_batch_parse` 는 `[N]` 으로 시작하지 않는 줄을 앞 수식에 이어 붙인다. 모델이 해설을
덧붙이면 그게 수식이 되어 점역까지 흘러갔다. storage 산출물 실측에서 수식 출력
10,417개 중 47개가 이 상태였다.
"""
from app.ai.llm.formula_opt import _batch_parse, _drop_commentary


def test_꼬리_해설을_걷어_낸다():
    t = "x^{2} + y^{2} = r^{2}\n- `2 π`는 `2π`로 붙여 표기를 통일했습니다."
    assert _drop_commentary(t) == "x^{2} + y^{2} = r^{2}"


def test_머리_해설도_걷어_낸다():
    t = "주어진 LaTeX 수식을 분석하겠습니다.\n\\frac{a}{b}"
    assert _drop_commentary(t) == "\\frac{a}{b}"


def test_해설만_있으면_원본을_지킨다():
    # 다 걷어 내면 수식이 빈다 — 안 고친 것이 빈 것보다 낫다.
    t = "교정된 LaTeX를 아래에 제시합니다."
    assert _drop_commentary(t) == t


def test_수식은_건드리지_않는다():
    for t in ("\\sqrt{2}\\sin t - 1 = 0", "a_{n+2} = \\frac{a_{n+1}^{2}}{a_{n}}",
              "\\text{넓이} = 3a \\times a"):
        assert _drop_commentary(t) == t


def test_배치_응답에서도_걷어_낸다():
    resp = ("[1] x + 1 = 0\n"
            "- 불필요한 공백을 정리했습니다.\n"
            "[2] y = 2x\n")
    assert _batch_parse(resp, 2) == ["x + 1 = 0", "y = 2x"]


def test_배치_개수가_어긋나면_종전대로_버린다():
    assert _batch_parse("[1] x = 1\n", 2) is None
