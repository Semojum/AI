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


def test_line_start_double_circle_is_a_bullet():
    """◎ 줄머리 단독 = 제72항 동그라미 글머리 ⠸⠴.

    실물 014 body p69·p77·p143·p147(서술형 평가 지면 "◎ 문제:" · "◎ 학생 답안")에서
    gold 줄머리 ⠸⠴ 개수가 묵자 ◎ 개수와 2:2 · 2:2 · 1:1 · 2:2로 맞는다.
    """
    assert tr("◎ 문제: 갑과 을").startswith("⠸⠴")
    assert tr("◎ 학생 답안").startswith("⠸⠴")


def test_line_start_triangle_is_a_caption_bullet():
    """▲ 줄머리 = 그림 캡션 머리. gold가 ⠸⠲로 적는다(012 body p9 대조)."""
    assert tr("▲ 다원커우 토기").startswith(BULLET)


def test_black_square_run_is_a_mask_not_bullets():
    """■런 두 개 이상 = 이름 가림. gold 013 ans p0024 "■■ 대학교는" → ⠸⠶⠶⠇.

    개수로 가른다 — 글머리는 겹치지 않고 가림은 겹친다. 위치로 가르면 추출이 요소를
    잘라 온 자리에서 문중이 줄머리처럼 보여 헛나간다.
    """
    assert "⠸⠶⠶⠇" in tr("■■ 대학교는")
    assert "⠸⠶⠶⠇" in tr("앞의 ■■ 회사")
    assert tr("■ 도입: 디지털").startswith(BULLET)     # 홑 ■는 그대로 글머리


def test_double_corner_brackets_use_regulation_cells():
    """겹낫표 『』 = ⠰⠦ … ⠴⠆ (규정 문장부호표). 종전에는 작은따옴표로 바뀌었다.

    gold 실측: 묵자 『 val 412 · dev 11 대 gold ⠰⠦ val 422 · dev 11(1:1).
    우리는 val 1 · dev 2뿐이었다 — 책 제목이 통째로 다른 부호로 나갔다.
    ⚠ 홑낫표 「」는 아직 관행(작은따옴표)을 쓴다. gold ⠐⠦에 다른 용도가 섞여 있어
      실물을 짚기 전까지 건드리지 않는다.
    """
    out = tr("『세종실록지리지』")
    assert out.startswith("⠰⠦") and out.endswith("⠴⠆")
    assert tr("「홑낫표」 자리").startswith("⠠⠦")     # 홑낫표는 종전 그대로


def test_line_start_hyphen_bullet_is_one_cell():
    """줄머리 붙임표 글머리 = ⠤ 한 칸 + 한 칸 띄움(규정 제72항 글머리 기호표).

    종전에는 ⠤⠤(두 칸)에 뒤 공백도 없이 붙였고 근거가 구판 실측이었다. 신규 gold는
    한 칸+공백을 dev 312·val 208회 쓰고 우리는 0회였다(실물 val 005 body p0009).
    """
    assert tr("- 존대 표현과").startswith("⠤⠀")
    assert not tr("- 존대 표현과").startswith("⠤⠤")


def test_wave_dash_is_not_dropped():
    """U+301C 물결 대시 〜도 물결표다. 표에 없어 조용히 사라졌다(코퍼스 0회라 예방용)."""
    for ch in ("~", "∼", "〜"):
        assert "⠈⠔" in tr(f"01{ch}02"), ch


def test_unlisted_shape_runs_become_first_definition_mask():
    """규정 표에 없는 도형이 겹치면 이름 가림 — 제1 정의 ⠸⠔ⁿ⠇로 내고 개수를 보존한다.

    제57항 [붙임]이 ○ × △ 이외를 제1~제3 점역자 정의로 위임하므로 어느 정의든 규정
    준수이고, 조용히 지우는 것만 위반이다(plan 실물 8종 34회).
    """
    assert tr("♧♧대 언론학과").startswith("⠸⠔⠔⠇")
    assert tr("▽▽ 자연사 박물관").startswith("⠸⠔⠔⠇")
    assert "⠸⠔" not in tr("▼ 소회의실 1")     # 홑 글자는 가림이 아니다


def test_arrow_after_explain_label_becomes_colon():
    """해설 라벨 뒤 ▶ = 구분 표시. gold는 쌍점으로 적는다(012 body p0014).

    앞말 실측 129회 중 '정답 해설' 63 · '오답 피하기' 63. 나머지 3회는 gold 자신이
    갈려(본문 중 화살표 · 따옴표 안 생략) 규칙으로 만들 근거가 없어 건드리지 않는다.
    """
    assert "⠐⠂" in tr("정답 해설 ▶ 자료에서")
    assert "⠐⠂" in tr("오답 피하기 ▶ 첫째")
    assert "⠐⠂" not in tr("2배 성장했다. ▶ 관련 기사")   # 본문 중은 그대로 둔다
