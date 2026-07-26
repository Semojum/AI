"""아래아 ㆍ(U+318D)를 가운뎃점으로 쓰는 조판 관행 회귀 가드 — C5(수표) 계열.

이 파일이 지키는 것: 한글 음절 사이에 낀 ㆍ(U+318D)가 가운뎃점 점형 ⠐⠆로 나가는 것.
교재 조판이 ·(U+00B7) 자리에 한글 자모 아래아 ㆍ(U+318D)를 쓰면(같은 페이지에서 두 형태가
섞여 나온다 — 사회문화 p043) braillify가 이를 자모로 보고 **⠐⠼** 로 적었다. 뒤 셀 ⠼는
수표라 이어지는 한글이 통째로 숫자로 읽힌다 — '사회ㆍ문화' → 역점역 '사회,570와'.
한 코드포인트 차이가 낱말을 통째로 깨뜨리는 자리라 점수가 아니라 **글자**가 걸린 문제다.

**순환검증 금지**: 기대값은 두 출처에서만 왔다.
  ① 「한국 점자 규정」제50항 — 가운뎃점 · = `"2`(⠐⠆), 앞뒤를 모두 붙여 적는다
     (`braille-source/text/규정_텍스트.txt` 2327행, 예시 '정치·경제' = `.];o"2@].n`).
  ② 정답 도서 실측 — 사회문화 p045 gold `⠇⠚⠽⠐⠆⠑⠛⠚⠧`(사회·문화),
     언어 p291 gold `⠫⠁⠐⠆⠏⠒⠑⠶⠐⠆⠫⠢⠨⠻`(생각·원망·감정의).
     둘 다 원문이 U+318D인 자리다(추출 JSON 실측).
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator
from app.utils.braille_ascii import ascii_to_unicode
from app.utils.braille_back import decode

ARAEA = "ㆍ"      # ㆍ HANGUL LETTER ARAEA
MIDDOT = "·"     # · 가운뎃점


def test_규정_제50항_가운뎃점_점형() -> None:
    """제50항 예시 '정치·경제' = `.];o"2@].n` — 가운뎃점 셀이 ⠐⠆임을 규정 원문으로 고정."""
    reg = ascii_to_unicode('.];o"2@].n', backtick="space")
    assert "⠐⠆" in reg
    assert translator.translate_tagged_text("정치·경제") == reg


# (라벨, 원문, gold 셀열) — gold는 정답 도서 실측값, 우리 출력이 아니다.
CASES = [
    ("사회문화-p045", f"사회{ARAEA}문화", "⠇⠚⠽⠐⠆⠑⠛⠚⠧"),
    ("언어-p291", f"생각{ARAEA}원망{ARAEA}감정의", "⠠⠗⠶⠫⠁⠐⠆⠏⠒⠑⠶⠐⠆⠫⠢⠨⠻⠺"),
]


@pytest.mark.parametrize("label,src,gold", CASES, ids=[c[0] for c in CASES])
def test_아래아_가운뎃점_점형(label: str, src: str, gold: str) -> None:
    out = translator.translate_tagged_text(src)
    assert out == gold, f"{label}\n  gold: {gold}\n  우리: {out}"
    # 같은 자리의 정상 가운뎃점과 결과가 같아야 한다(코드포인트 차이가 결과를 바꾸면 안 됨).
    assert out == translator.translate_tagged_text(src.replace(ARAEA, MIDDOT))


@pytest.mark.parametrize("label,src,gold", CASES, ids=[c[0] for c in CASES])
def test_아래아_수표혼입_없음(label: str, src: str, gold: str) -> None:
    """수표 ⠼가 섞이면 뒤 한글이 숫자로 읽힌다 — 원문에 숫자가 없으면 ⠼도 없어야 한다."""
    out = translator.translate_tagged_text(src)
    assert "⠼" not in out, f"{label}: 수표 혼입 — {out}"
    back = decode(out)
    assert back == src.replace(ARAEA, MIDDOT), f"{label}: 역점역 불일치 — {back}"


def test_아래아_낱자_용법은_보존() -> None:
    """가드 — 한글 음절 사이가 아닌 ㆍ(진짜 아래아 자모)는 건드리지 않는다.

    국어 교재가 옛한글 모음을 다루는 자리는 따옴표·자모 나열 문맥이라 이 규칙이 안 걸린다.
    코퍼스 실측 6건은 전부 가운뎃점 용법(사회ㆍ문화·생각ㆍ원망ㆍ감정)이고 자모 용법 0건이나,
    자모 용법이 나타나도 조용히 바뀌지 않게 경계를 고정한다.
    """
    for src in (ARAEA, f"‘{ARAEA}’는 아래아다", f"자모 {ARAEA} 는"):
        assert translator._ARAEA_MIDDOT_RE.search(src) is None, src
