"""B-10(원장) 도형 기호 — 글머리 갈래와 숨김표 갈래를 위치로 가른다.

근거는 **규정**이다(제72항 글머리 · 제57항 숨김표 · 제58항 빠짐표).
gold 대조는 확인용이고, ■ ● ▣ 용례는 holdout에 몰려 있어 dev·val 지표로는 안 보인다.
"""
from app.ai.braille.translator import translate_tagged_text as tr

BULLET = "⠸⠲"          # 제72항 • 글머리
MASK_1 = "⠸⠴⠇"         # 제57항 숨김표 ○ 한 개
MASK_2 = "⠸⠴⠴⠇"        # 제57항 숨김표 ○ 두 개
FILL_3 = "⠸⠶⠶⠶⠇"       # 제58항 빠짐표 □ 세 개


def test_black_shapes_are_bullets():
    """■ ● ▣ 는 글머리다 — 종전에는 문자표에 없어 통째로 사라졌다."""
    for mark in ("■", "●", "▣"):
        assert tr(f"{mark} 항목").startswith(BULLET), mark


def test_big_circle_midline_is_mask():
    """문중 ◯◯ = 이름 가림 → 제57항 숨김표. gold도 ⠸⠴⠴⠇ 다."""
    assert MASK_2 in tr("다음 ◯◯ 부족은")


def test_big_circle_at_line_start_is_left_alone():
    """줄머리 ◯ 는 표 셀 값(◯는 있음)이라 숨김표로 만들면 안 된다.

    추출이 표 셀을 한 줄에 하나씩 뱉어 줄머리처럼 보인다. gold는 로마자 O·X로 적는다.
    """
    assert MASK_1 not in tr("◯는 있음")


def test_single_big_circle_is_left_alone():
    """홑 ◯ 은 가림이 아니다 — 표 범례·값 자리다.

    gold 실측(dev+val 전수): 숨김표 틀 한 칸이 dev 18 · val 0인데 두 칸은 dev 181 · val 277.
    홑 ◯ 까지 태웠더니 우리 한 칸 틀이 dev 116 → 313으로 뛰었다(gold 18). 되돌린 근거다.
    """
    assert "⠸" not in tr("표에서 ◯는 있음")


def test_big_circle_run_is_judged_as_a_whole():
    """런 단위 판정 — 글자 단위로 하면 줄머리 ◯◯의 둘째만 바뀌어 없는 뜻이 된다."""
    assert tr("◯◯ 신문").count("⠸") == 0


def test_box_run_is_fill_not_x():
    """□ 는 빠짐표(제58항)다. ×의 숨김표 점형(제57항)이 아니다."""
    assert FILL_3 in tr("아음은 □□□의 석 자다")
    assert "⠸⠭⠭⠭⠇" in tr("이 ×××야")     # × 경로는 그대로
