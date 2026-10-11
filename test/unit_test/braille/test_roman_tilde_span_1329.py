"""#1329 — 국어 문장 안 로마자 사이 물결(`A~F`)은 로마자 구간 하나다. 닫았다 다시 열지 않는다."""
from app.ai.braille import translator as T


def test_로마자_사이_물결은_구간을_닫고_다시_열지_않는다():
    # 「한국 점자 규정」(재추출) 제29항 1496~1498행: 로마자가 둘 이상 연이어 나오면 첫 로마자 앞에 로마자표(0 = ⠴),
    #   마지막 로마자 뒤에 종료표(4 = ⠲). 제32항 1650행: 그 사이는 통일영어점자. 물결 ⠈⠔ 는 두 규정 점형이 같다
    #   (제33항 [다만] 1677~1679행 '/ - ~'). gold dev · val `A~F` 꼴 274곳이 이 꼴이고 닫고 다시 여는 꼴은 0곳.
    out = T.translate_tagged_text("시험관 A~F에")
    assert "⠴⠠⠁⠈⠔⠠⠋⠲" in out
    assert "⠲⠈⠔⠴" not in out


def test_붙임표는_종전대로_뒤_낱자에_1종_지시자를_적는다():
    # 제36항 예문(재추출 1793~1794행) `v-x쪽` = 0v-;x4 = ⠴⠧⠤⠰⠭⠲ — 붙임표 뒤 낱자는 홀로 선 글자라 ⠰. 물결 뒤는 아니다.
    assert T.translate_tagged_text("v-x쪽").startswith("⠴⠧⠤⠰⠭⠲")
    assert "⠈⠔⠰" not in T.translate_tagged_text("시험관 A~F에")


def test_한글_없는_줄과_숫자_물결은_그대로다():
    assert "⠴" not in T.translate_tagged_text("A~B~C")          # 제29항 [다만] 문단 전체가 로마자 — 표 생략
    assert T.translate_tagged_text("1~5에서").startswith("⠼⠁⠈⠔⠼⠑")
