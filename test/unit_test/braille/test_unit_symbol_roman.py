"""단위 기호 로마자표(제69항) 회귀 가드 — 한컴 좁은 공백 백틱이 단위를 수식으로 먹던 결함.

이 파일이 지키는 것: 숫자 뒤 로마자 단위 기호는 **로마자표 ⠴ … 로마자 종료표 ⠲** 안에
적힌다(제69항). 한컴/MinerU 추출이 '40 mmHg'의 좁은 공백을 백틱으로 흘려 '40`mmHg'가
되면, 백틱 수식 라우팅(`_BACKTICK_MATH_RE`)이 단위를 수식 구간으로 가져가 로마자표·종료표가
통째로 빠졌다. 그 결과 로마자가 한글 점형으로 읽혀 **역점역하면 글자가 깨진다**
(⠍⠍⠠⠓⠛ → '우우툰'). 이 파일은 그 자리에 로마자표가 서 있는지, 그리고 역점역이 원래
로마자를 되돌리는지를 본다.

**순환검증 금지**: 기대값은 두 출처에서만 왔다.
  ① 「한국 점자 규정」제69항 원문 예시 BRF (`braille-source/text/규정_텍스트.txt` 2693행~).
     조항: "로마자로 쓰인 단위 기호는 그 앞에 로마자표를 적고 그 뒤에 로마자 종료표를
     적는다. 이때 제37항의 규정에 따라 묶음 약자를 사용하고, 띄어쓰기는 묵자를 따른다."
  ② 정답 도서 실측 — 생물 p081 gold(`test_data/output/output_생물_page081.brl`)에서
     '40 mmHg'가 ⠼⠙⠚⠴⠍⠍⠠⠓⠛(⠲)로 8회 일관 표기.
생산 코드의 출력을 기대값으로 삼은 케이스는 하나도 없다.

**규정 BRF는 backtick="space"** 관례다(코퍼스 gold의 backtick="cell"과 **반대**).
대조는 `test_roman_span_regulation.py`와 같은 이유로 **셀만** 본다 — 규정 원문이 32칸 줄로
접혀 있어 줄끝 채움 백틱과 진짜 칸 띄우기를 구별할 수 없다.
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator
from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode

_BLANK = "⠀"

# (라벨, 원문, 제69항 원문 BRF)
REG_CASES = [
    ("69-a", "1m는 100cm이다.", "``#a0m4cz`#ajj0cm4oi4"),
    ("69-b", "운동으로 한 달 동안 7 kg을 감량했다.",
     '``gi={"u`j3`i1`i=<3`#g`0kg4!`$5`">7jr/i4'),
    ("69-c", "그의 혈당 수치가 160㎎/㎗를 넘었다.",
     '``@[w`j\\i7`,m;o$`#afj0mg_/dl4"!`cs5s/i4'),
    ("69-d", "최근 USB 메모리 256GB는 5만 원대 가격이다.",
     '``;y@z`0,,usb4`eneu"o`#bef0,,gb4cz`#e`e3`p3ir`$@:aoi4'),
]


def _cells(s: str) -> str:
    return "".join(ch for ch in s if 0x2800 <= ord(ch) <= 0x28FF and ch != _BLANK)


@pytest.mark.parametrize("label,src,gold_brf", REG_CASES, ids=[c[0] for c in REG_CASES])
def test_규정_제69항_단위_예시(label: str, src: str, gold_brf: str) -> None:
    ours = _cells(translator._safe_to_unicode(src))
    reg = _cells(ascii_to_unicode(gold_brf, backtick="space"))
    assert ours == reg, f"제69항 {label} 불일치\n  원문: {src}\n  규정: {reg}\n  우리: {ours}"


# 원문에 좁은 공백 백틱이 낀 실제 추출 형태(생물 p081·p103·p110, dev+val 89회).
# 기대 셀열은 gold 생물 p081 실측(⠼⠙⠚⠴⠍⠍⠠⠓⠛⠲보다) — 우리 출력이 아니다.
BACKTICK_CASES = [
    ("mmHg-조사붙음", "40`mmHg보다", "⠴⠍⠍⠠⠓⠛⠲", "mmHg"),
    ("mmHg-공백", "40`mmHg 이하이다.", "⠴⠍⠍⠠⠓⠛", "mmHg"),
    # 생물 p081 원문 그대로. 요소 첫머리가 숫자면 별도 경로(수식 라우팅)가 선점하므로
    # 실제 코퍼스 형태인 문장 문맥으로 둔다.
    ("L-빗금", "ㄷ. (나)의 폐포에서 공기 흡입량은 약 2.5`L/분이다.", "⠴⠠⠇", "L"),
    ("g-단위", "1`g당 약 9`kcal의 열량을 낸다.", "⠴⠅⠉⠁⠇", "kcal"),
]


@pytest.mark.parametrize("label,src,must_have,roman", BACKTICK_CASES,
                         ids=[c[0] for c in BACKTICK_CASES])
def test_좁은공백_백틱_단위에도_로마자표(label: str, src: str,
                                        must_have: str, roman: str) -> None:
    out = translator.translate_tagged_text(src)
    assert must_have in out, f"{label}: 로마자표 구간 {must_have} 없음 — {out}"
    # 결함의 본질은 점수가 아니라 '깨진 글자'다 — 역점역으로 로마자가 살아있는지 본다.
    assert roman in decode(out), f"{label}: 역점역에 {roman} 없음 — {decode(out)}"


def test_백틱_수식은_그대로_수식으로() -> None:
    """가드 — 백틱 뒤가 괄호·따옴표·연산자를 낀 진짜 수식이면 종전대로 수식 라우팅.

    코퍼스 전수에서 '백틱 앞이 숫자'인 수식 라우팅 92건 중 6건이 이 형태다
    (f'(a)·f'(b)·f'(c)·f(x)·sinh+cosh). 단위 규칙이 이들을 가져가면 안 된다.
    """
    for src in ("그림에서 4`f'(a)의 값", "2`f(x)의 값", "값 3`sinh+cosh는"):
        assert translator._UNIT_BACKTICK_RE.search(src) is None, src


# ── 역방향(제69항) — 규정 원문 쌍이 기대값이다 (2026-09-06) ──────────────────
# 출처는 위와 같다: `braille-source/text/규정_텍스트.txt` 2693행~(제69항).
# 생산 코드의 출력을 기대값으로 쓴 케이스는 없다.
REV_CASES = [
    # 제69항 본문 — 로마자로 쓰인 단위는 묵자에서도 로마자다(사각문자 ㎝·㎏ 아님).
    ("69-rev-cm", "#a0m4cz`#ajj0cm4oi4", "1m는 100cm이다."),
    ("69-rev-kg", "#g`0kg4!", "7 kg을"),
    ("69-rev-in", "#a0in4cz`#b4ed0cm4oi4", "1in는 2.54cm이다."),
    # [붙임1] — μm 은 그리스 접두가 붙고(⠴⠨⠍⠍⠲), 접두 없는 ⠴⠍⠍⠲ 는 mm 이다.
    ("69-rev-mm", "#a`0mm4oi4", "1 mm이다."),
    # [붙임3] — 빗금으로 이어진 단위는 한 구간이다. ⠸⠌ 에서 런을 끊으면 안 된다.
    ("69-rev-slash", "#afj0mg_/dl4", "160mg/dl"),
    # [붙임2] — 단위표 뒤 한 칸 너머의 ⠲ 는 마침표지 로마자 종료표가 아니다.
    ("69-rev-pct-p", "#a`0pp`i4", "%p"),
]


@pytest.mark.parametrize("label,brf,expect", REV_CASES, ids=[c[0] for c in REV_CASES])
def test_규정_제69항_역점역(label: str, brf: str, expect: str) -> None:
    got = decode(ascii_to_unicode(brf.replace("`", " "), backtick="space"))
    assert expect in got, f"{label}: 기대 {expect!r} 없음 — {got!r}"
