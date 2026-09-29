"""T25 — 기호표에도 braillify 에도 없는 기호가 조용히 사라지던 것.

① 지우되 세고 그 쪽에 R17 을 세운다(PUA 의 R15 와 같은 원칙).
② 한자·보이지 않는 글자·백틱·다른 문자권 글리프는 세지 않는다 — 빼는 게 맞는 것이고,
   세면 2027 8권에 2,500회가 넘어 플래그가 늘 켜진다.
③ 한자 병기 괄호를 지울 때 앞 빈칸도 지운다(gold `측은지심을`).
"""
import pytest

from app.ai.braille.translator import dropped_symbols, translate_body


def test_사라지는_기호를_센다():
    # 2027 실물: 별점(사회문화 dv-004 p173) · 댓글 표시(p011) · 글머리 ▶
    got = dropped_symbols("가▶나 ★★★★☆ ↳ 고양이랑")
    assert got == {"★": 4, "▶": 1, "↳": 1}


def test_해설_라벨_뒤_화살표는_쌍점이라_안_센다():
    assert not dropped_symbols("정답 해설 ▶ 자료에서 오답 피하기 ▶ ① 원의")


def test_실제로_사라지는_자리다():
    assert translate_body("가▶나")[0] == translate_body("가나")[0]


@pytest.mark.parametrize("text", [
    "측은지심(惻隱之心)을",      # 한자 — gold 도 뺀다
    "ㄷ. ‌5와 6 사이",       # ZWNJ
    "10`nm~100`nm",              # 백틱 추출 잡음
    "١ ٣ ང ࿒",                   # 다른 문자권 글리프 잡음
])
def test_빼는_게_맞는_글자는_안_센다(text):
    assert not dropped_symbols(text)


@pytest.mark.parametrize("ch", list("○△□×◎▣☆◇◆※→←·…‘’“”「」『』〈〉《》①②㉠㉡"))
def test_점형이_있는_기호는_안_센다(ch):
    assert not dropped_symbols(f"가{ch}나")


def test_한자_괄호_앞_빈칸도_지운다():
    # vl2027-EBS-E26-014 p005 gold `⠰⠪⠁⠵⠨⠕⠠⠕⠢⠮`(측은지심을)
    assert translate_body("측은지심 (惻隱之心)을 확충")[0] == translate_body("측은지심을 확충")[0]
    # 뒤가 빈칸이면 빈칸 하나는 어절 경계로 남는다(종전 두 칸)
    assert translate_body("국가 (國家) 가")[0] == translate_body("국가 가")[0]
    # 기입용 빈 괄호는 그대로 둔다
    assert "⠦⠄⠀⠠⠴" in translate_body("공백 (   )이/가")[0][0]
