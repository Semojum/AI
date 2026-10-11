"""줄 머리 배지 라벨 → `(라벨)`(원장 C-144). 묵자엔 괄호가 없고 gold 는 감싼다(`(문제 분석) 갑은 …`).

라인 dict 는 PyMuPDF rawdict 형식을 본떠 손으로 짓는다(순환 검증 금지). 글꼴 · 크기는 생활과 윤리 해설 묵자 실측
(배지 NanumSquareOTFB 6.5pt · 본문 YDVYMjOStd12 9.0pt)을 따랐다.
"""
import pytest

from app.ai.preprocessor.pdf_analyzer import _line_text_with_word_gaps

BADGE, BODY = ("NanumSquareOTFB", 6.5), ("YDVYMjOStd12", 9.0)


def _line(*spans) -> dict:
    """(글, 글꼴, 크기) 조각들 → rawdict 줄. 글자 폭 5pt, 빈칸 글리프를 그대로 둔다."""
    out, x = [], 0.0
    for text, font, size in spans:
        chars = []
        for c in text:
            chars.append({"c": c, "bbox": (x, 0.0, x + 5.0, 10.0)})
            x += 5.0
        out.append({"size": size, "flags": 4, "font": font, "chars": chars})
    return {"spans": out}


def test_줄_머리_배지_라벨을_소괄호로_감싼다():
    line = _line(("문제 분석", *BADGE), (" 갑은 공자, 을은", *BODY))
    assert _line_text_with_word_gaps(line, italic=True) == "(문제 분석) 갑은 공자, 을은"


def test_줄_머리_빈칸은_건너뛰고_본다():
    line = _line((" ", *BODY), ("참고", "NanumSquareRoundOTFEB", 7.0), (" 방정식의 해", *BODY))
    assert _line_text_with_word_gaps(line, italic=True) == " (참고) 방정식의 해"


@pytest.mark.parametrize("line", [
    _line(("정답과 해설", "YDVYGOStd31", 6.1), ("3", "DINPro-Regular", 9.0)),     # 쪽 머리말 — 뒤 글이 쪽 번호뿐
    _line(("선생님", "YDVYGOStd12", 7.3), (": 추가 탐구를 잘했다", *BODY)),          # 말하는 이 표지
    _line(("즉,", "YDVYMjOStd12", 6.6), (" 이 값은 양수", "EHsang-Italic", 9.0)),     # 부호 섞인 토막
    _line(("문제 분석", *BODY[:1], 6.5), (" 갑은 공자", *BODY)),                       # 같은 글꼴
    _line(("문제 분석", BADGE[0], 9.0), (" 갑은 공자", *BODY)),                        # 작지 않다
    _line(("예", *BADGE), (" 갑은 공자", *BODY)),                                      # 한 글자
    _line(("가나다라마바사아자차카타파", *BADGE), (" 갑은 공자", *BODY)),               # 13자
    _line(("①", *BADGE), (" 갑은 공자", *BODY)),                                      # 한글 아님
])
def test_라벨_꼴이_아니면_안_감싼다(line):
    assert "(" not in _line_text_with_word_gaps(line, italic=True)


@pytest.mark.parametrize("size, wrapped", [(7.2, True), (7.8, False)])   # 크기비 0.80(라벨 최대) · 0.867(라벨 아닌 후보 최소 언저리)
def test_크기비_문턱(size, wrapped):
    line = _line(("문제 분석", BADGE[0], size), (" 갑은 공자", *BODY))
    assert _line_text_with_word_gaps(line, italic=True).startswith("(문제 분석)") is wrapped


def test_호출부가_안_켜면_종전_글():
    line = _line(("문제 분석", *BADGE), (" 갑은 공자", *BODY))
    assert _line_text_with_word_gaps(line) == "문제 분석 갑은 공자"


def test_스위치를_끄면_종전(monkeypatch):
    monkeypatch.setenv("BADGE_LABEL", "0")
    line = _line(("문제 분석", *BADGE), (" 갑은 공자", *BODY))
    assert _line_text_with_word_gaps(line, italic=True) == "문제 분석 갑은 공자"
