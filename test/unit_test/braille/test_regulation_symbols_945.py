"""#945 — 규정 예문과 어긋나던 기호 넷(「한국 점자 규정」 제31·49·53·71·72항).

기대값은 규정 원문 BRF(`braille-source/text/한국 점자 규정_재추출.txt`)를 그대로 옮겼다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def _brf(s: str) -> str:
    return ascii_to_unicode(s, backtick="space")


# ── 제31항 국어 문장 속 그리스 문자 ────────────────────────────────────────────
def test_제31항_소문자():
    # 1645행 `통계에서 σ는` = `h=@/n,s`0.s4cz`
    assert _body("통계에서 σ는 표준").startswith(_brf("h=@/n,s`0.s4cz"))


def test_제31항_대문자_단어():
    # 대문자 둘 이상은 대문자 단어표 ⠠⠠ 하나에 글자마다 ⠨ — `ΦΒΚ의` = `0,,.f.b.k4w`
    assert _brf("0,,.f.b.k4w") in _body("그녀는 ΦΒΚ의 회원이다.")


def test_그리스_gold_2027_실물():
    # 생명과학 E26-001 p130 `α세포` · 수학 E26-009 p071 `각 θ에` · p135 `기호 Σ를`
    assert _body("α세포, β세포에서").startswith("⠴⠨⠁⠲⠠⠝⠙⠥")
    assert "⠴⠨⠹⠲⠝" in _body("각 θ에 대하여")
    assert "⠴⠠⠨⠎⠲⠐⠮" in _body("합의 기호 Σ를 사용하여")


def test_그리스_식과_단위는_그대로():
    assert "⠴" not in _body("α+β+γ=7")          # 한글이 없으면 손대지 않는다
    assert _body("5μm") == "⠼⠑⠴⠨⠍⠍⠲"            # 제69항 [붙임 1] 단위 경로


# ── 제71항 [다만] 감싼 기호 ────────────────────────────────────────────────────
def test_제71항_저작권():
    # 2868행 `저작권자© 연합뉴스` = `.s.a@p3.0^c4`*jbc%,{`
    assert _body("저작권자© 연합뉴스") == _brf(".s.a@p3.0^c4`*jbc%,{")


def test_제71항_등록상표_상표_문단():
    assert _body("®는 등록 상표").startswith("⠴⠘⠗⠲⠉⠵")
    assert "⠴⠘⠞⠲⠐⠥" in _body("상표 기호는 ™로 표시한다.")
    assert "⠀⠴⠘⠏⠲⠀" in _body("나타낼 때 ¶ 기호를 사용하였다.")


def test_제71항_뒤에_숫자면_종료표_없음():
    # 2862행 `(헌법§1①)` = `…0^s#a#1,04`
    assert "⠴⠘⠎⠼⠁⠼⠂" in _body("대한민국은 민주공화국이다(헌법§1①).")


# ── 제49항 가림 × ─────────────────────────────────────────────────────────────
def test_제49항_가림표():
    # 예문 `×란 말이` · 2027 gold 사회문화 E26-005 p115 `×월 ×일` = ⠸⠭⠇⠏⠂ ⠸⠭⠇⠕⠂
    assert "⠸⠭⠇⠐⠣⠒" in _body("그 말을 듣는 순간 ×란 말이")
    assert "⠸⠭⠇⠏⠂⠀⠸⠭⠇⠕⠂" in _body("2026년 ×월 ×일 재윤이가")


def test_맞고_틀림_표시는_그대로():
    assert "⠴⠠⠭⠙⠬" in _body("틀린 것에 ×표 하시오.")          # 가위표 이름
    assert "⠴⠠⠭⠝" in _body("맞으면 ◯에, 틀리면 ×에 표시해")  # ◯ 가 같이 있다
    assert _body("※ ◯ 또는 ×").endswith("⠴⠠⠭")
    assert "⠡" in _body("임금×성별 근로자 수")                  # 곱셈


# ── 제72항 [붙임] ○ 와 함께 나온 ◎ ───────────────────────────────────────────
def test_제72항_붙임_이중원():
    lines = translate_body("◎ 실장급 인사발령\n○ 승진 인사")[0]
    assert lines[0].startswith("⠸⠴⠴⠀")


def test_이중원_홀로면_종전대로():
    assert _body("◎ 문제 : 종교에").startswith("⠸⠴⠀")


# ── 제72항 [붙임] □ 와 함께 나온 ▣ (#1106) ──────────────────────────────────────
def test_제72항_붙임_채운네모():
    # 2912~2913행 "○, □가 ◎, ▣와 함께 나와 구별해야 할 때 ◎는 _00으로, ▣는 _77으로 적어 나타낸다."
    lines = translate_body("□ 주제\n▣ 일시: 10월 4일")[0]
    assert lines[1].startswith(_brf("_77`"))


def test_채운네모_함께가_아니면_종전대로():
    # [붙임] 밖은 원장 B-10 관행 ⠸⠲(제72항 표의 • `_4`)를 지킨다. ○ 는 ▣ 의 짝이 아니고 □□ 는 숨김표다.
    assert _body("▣ 일시: 10월 4일").startswith(_brf("_4`"))
    assert translate_body("○ 승진 인사\n▣ 일시")[0][1].startswith(_brf("_4`"))
    assert translate_body("□□고 여러분\n▣ 일시")[0][1].startswith(_brf("_4`"))


# ── 제53항 [다만] 줄임표 개수 ─────────────────────────────────────────────────
def test_제53항_개수를_밝힐_때():
    # 2395행 `‘……’이 원칙이나 ‘…’나 ‘...’도` = `,8,,,,,,0'o` · `,8,,,0'c` · `,84440'iu`
    out = _body("줄임표는 ‘……’이 원칙이나 ‘…’나 ‘...’도 허용된다.")
    assert _brf(",8,,,,,,0'o") in out and _brf(",8,,,0'c") in out and _brf(",84440'iu") in out


def test_문장_속_줄임표는_한_부호():
    assert _body("그는…… 말했다").startswith("⠈⠪⠉⠵⠠⠠⠠⠀")


def test_연산_기호_뒤_그리스는_식이다():
    # 수학 E26-009 p079 gold `각 -θ가` = ⠔⠨⠹ (수식꼴, 감싸지 않음)
    assert "⠴⠨⠹⠲⠫" not in _body("(ii) 각 θ와 각 -θ가 나타내는")


def test_로마자_뒤_기호는_잡음이라_감싸지_않는다():
    # 생명과학 E26-001 p068 추출 잡음 `X\x8c`¶`Y`(윗첨자가 ¶ 로 읽힘) — 로마자 뒤라 두 칸을 얹지 않는다
    assert "⠴⠘⠏⠲" not in _body("아버지는 X\x8c`¶`Y, 자녀 1은 X\x8c`¶`X\x8c`¶`를")


def test_그리스_뒤_도_단위는_종료표_없음():
    # 수학 E26-009 p067 gold `α°라 하면` = ⠴⠨⠁⠴⠙⠀⠐⠣ (단위 뒤 한 칸은 제69항 [붙임 2])
    assert "⠴⠨⠁⠴⠙⠀⠐⠣" in _body("한 각의 크기를 α°라 하면")


def test_그리스_뒤_괄호는_종료표_없음():
    # 같은 쪽 gold `크기가 θ(라디안)인` = ⠴⠨⠹⠦⠄⠐⠣⠊⠕⠣⠒⠠⠴⠟
    assert "⠴⠨⠹⠦⠄⠐⠣⠊⠕⠣⠒⠠⠴⠟" in _body("중심각의 크기가 θ(라디안)인 부채꼴")
