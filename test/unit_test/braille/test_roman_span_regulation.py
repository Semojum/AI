"""로마자 구간(제32·33·35항) 규정 예시 리플레이 — 낱말이 아니라 **구간** 단위 처리 회귀 가드.

이 파일이 지키는 것: 로마자가 둘 이상 연이어 나올 때 첫 로마자 앞에만 로마자표를,
마지막 로마자 뒤에만 종료표를 적는다(제29·32항). 구간 **내부**의 쉼표·콜론은 통일영어점자
점형으로, 구간이 끝난 뒤 한글 앞에 오는 부호는 한글 점형으로 적고 종료표를 생략한다(제33항).
로마자와 숫자가 이어 나오면 종료표를 적지 않는다(제35항).

**순환검증 금지**: 기대값은 「한국 점자 규정」 원문 예시의 BRF를 그대로 옮긴 것이고 생산
코드로 만들지 않았다. 조항 위치 = `braille-source/text/규정_텍스트.txt` 제29항 1495행·
제32항 1649행·제33항 1666행·제34항 1708행·제35항 1719행.

**왜 정식 테스트로 옮겼나**(2026-07-27): 이 리플레이는 원래 `V2/temp/x1_replay.py`에만
있었는데 temp는 언제든 삭제되는 자리다. 독립 검증에서 "이 변경의 동작을 덮는 단위 테스트가
0건"이 유일한 미충족 사항으로 지적됐다 — `test_regulation_examples.py`는 공백이 든 쌍을
필터로 제외해서 여러 낱말 로마자 구간을 아예 안 본다.

**규정 BRF는 backtick="space"** 관례다(칸 띄우기·줄끝 채움). 코퍼스 gold(backtick="cell")와
**반대**라 반드시 space로 읽어야 한다 — 이걸 틀리면 측정이 통째로 무효가 된다.

대조는 **셀만** 본다: 규정 원문이 32칸 줄로 접혀 있어 줄끝 채움 백틱과 진짜 칸 띄우기가
구별되지 않기 때문이다(`,re<!`` + 개행 + `ju"` = '새마을호' 한 낱말). 이 규칙이 바꾸는 것은
전부 셀(⠲ 유무·⠐↔⠂)이라 셀 비교로 온전히 잡힌다.
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator
from app.utils.braille_ascii import ascii_to_unicode

_BLANK = "⠀"

# (라벨, 원문, 규정 BRF, 조항)
CASES = [
    # 제32항 — 구간 병합(쉼표·공백이 구간 내부)
    ("32-b", "식탁 위에 apples, bananas, grapes 등이 있다.",
     "``,oaha`mrn`0apples1`bananas1```grapes4`i{7o`o/i4", "32"),
    ("32-c", "평창 동계 올림픽의 SNS 계정은 pyeongchang 2018이다.",
     "``d};<7`i=@/`u1\"o5doaw`0,,sns4``@/.]z`0pye;g*ang`#bjahoi4", "32/35"),
    # 제35항 — 로마자 뒤 숫자면 종료표 없음
    ("35-a", "MP3 플레이어", "0,,mp#c`d!\"nos", "35"),
    ("35-b", "A4용지", "0,a#d+7.o", "35"),
    ("35-c", "LP 1장", "0,,lp`#a.7", "35"),
    ("35-d", "요즘에는 KF94 마스크가 필수입니다.",
     "``+.{5ncz`0,,kf#id`e,{f{$`do1,m`obcoi4", "35"),
    ("35-e", "새로운 MP4 Player를 출시했다.",
     "``,r\"ug`0,,mp#d`,play}4\"!`;&,ojr/i4", "35"),
    ("35-f", "KBS 1 TV 좀 켜 주세요.", "``0,,kbs`#a`,,tv4`.u5`f:`.m,n+4", "35"),
    ("35-g", "추가 내용은 Part 3을 참고하세요.",
     "``;m$`cr+7z`0,\"p`#c!`;<5@uj,n+4", "35"),
    # 제33항 — 한글 앞 문장부호는 한글형, 종료표 없음
    ("33-a", "우리나라 기차에는 KTX, 새마을호, 무궁화호 등이 있다.",
     "``m\"oc\"<`@o;<ncz`0,,ktx\"`,re<!``ju\"`em@m7jvju`i{7o`o/i4", "33"),
    ("33-b", "WHO: 세계 보건 기구", "0,,who\"1`,n@/`~u@)`@o@m", "33"),
]


def _cells(s: str) -> str:
    """점자 셀만 남긴다(빈칸 제외) — 줄 접힘·채움 백틱의 영향을 배제."""
    return "".join(ch for ch in s if 0x2800 <= ord(ch) <= 0x28FF and ch != _BLANK)


def _gold(brf: str) -> str:
    return _cells(ascii_to_unicode(brf, backtick="space"))


def _ours(text: str) -> str:
    return _cells(translator._safe_to_unicode(text))


@pytest.mark.parametrize("label,src,gold_brf,article",
                         CASES, ids=[c[0] for c in CASES])
def test_규정_로마자구간_예시(label: str, src: str, gold_brf: str, article: str) -> None:
    assert _ours(src) == _gold(gold_brf), (
        f"제{article}항 {label} 불일치\n  원문: {src}\n"
        f"  규정: {_gold(gold_brf)}\n  우리: {_ours(src)}"
    )


@pytest.mark.xfail(
    reason="통일영어점자 grade-1 지시부호 ⠰ 미구현 — 제32항이 UEB에 위임한 부분이고 "
           "셀이 늘어나므로 별도 A/B 대상. 초안 하네스는 이 자리를 gold에서 빼고 대조해 "
           "'12/12 통과'로 보고했으나 엄밀히는 11/12였다(2026-07-27 독립 검증). "
           "구현하면 이 xfail을 지울 것.",
    strict=True,
)
def test_규정_32a_grade1_지시부호() -> None:
    """제32항 'a, b, c' — gold는 낱자 b·c 앞에 grade-1 지시부호 ⠰를 둔다."""
    assert _ours("다음 a, b, c의") == _gold("``i<{5`0a1`;b1`;c4w")
