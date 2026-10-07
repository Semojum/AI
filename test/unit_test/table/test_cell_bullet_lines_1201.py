"""#1201 — 표 칸 안 글머리 항목은 항목마다 새 줄 3칸에서 `• ` 로 연다.

「점자 도서 제작 지침」 2장 3절 5. 1)(재추출 1433~1434행): 문단 시작 위치의 글머리 기호는 3칸에 표기하고
다음 글자는 한 칸 띄어 적는다. 기대 셀은 gold 수능특강 세계사(EBS-E26-015)에서 옮겼다.
"""
from app.ai.braille import table_braille as tb

# 세계사 p0042 꼴(문장 수준 표라 행 머리 뒤가 쌍점)
TABLE = ("성장|중앙아시아에서 서아시아로 이동, 이슬람 세계에서 용병 등으로 활약, 이슬람교로 개종\n"
         "발전|•바그다드에 입성하여 아바스 왕조의 칼리프로부터 칭호를 받음•예루살렘과 소아시아 지역으로 세력 확대\n"
         "쇠퇴|장기간 지속된 전쟁 및 왕조의 분열 → 멸망")
SEONGJANG = "⠀⠀⠠⠻⠨⠶⠐⠂⠀"           # gold p0042 26행 `  성장: `
BALJEON = "⠀⠀⠘⠂⠨⠾⠐⠂"              # gold p0042 29행 `  발전:`
ITEM1 = "⠸⠲⠀⠘⠈⠪⠊⠊⠪⠝"               # gold p0042 30행 `• 바그다드에`(앞빈칸 뺌)
ITEM2 = "⠀⠀⠸⠲⠀⠌⠐⠍⠇⠂⠐⠝⠢"            # gold p0042 34행 `  • 예루살렘`
MARSHALL, ARROW = "⠑⠠⠳", "⠪⠒⠕"      # gold p0144 22행 `• 마셜 … ↔`


def _body(text: str) -> list[str]:
    """테두리 · 행 구분선을 뺀 내용 줄."""
    return [ln for ln in tb._render_grid(text) if ln.strip("⠀") and not ln.startswith(("⠿", "⠐⠐"))]


def test_둘째_항목부터_새_줄_3칸이고_첫_항목은_이름표_줄에_둔다():
    body = _body(TABLE)                 # 이름표를 혼자 한 줄로 둘지는 따로 잰다(pm 10-07 20:35)
    assert any(ln.startswith(BALJEON + "⠀" + ITEM1) for ln in body)
    assert any(ln.startswith(ITEM2) for ln in body)
    assert len([ln for ln in body if ln.startswith("⠀⠀⠸⠲⠀")]) == 1


def test_글머리_없는_행은_그대로다():
    assert _body(TABLE)[0].startswith(SEONGJANG)


def test_끄면_종전대로_한_문단이다(monkeypatch):
    monkeypatch.setenv("TABLE_CELL_BULLET_BREAK", "0")
    body = _body(TABLE)
    assert not any(ln.startswith("⠀⠀⠸⠲") for ln in body)


def test_첫_칸이_글머리_목록이면_가운데_칸은_앞_항목_줄에_잇는다():
    body = _body("자본주의 진영||공산주의 진영\n•트루먼 독트린 발표•마셜 계획 발표|↔|•동유럽에 공산주의 세력 확대")  # 세계사 p0144 꼴
    assert len([ln for ln in body if ln.startswith("⠀⠀⠸⠲⠀")]) == 3
    assert any(MARSHALL in ln and ARROW in ln for ln in body)


def test_번호_체계_표도_항목마다_새_줄_3칸이다():
    out = tb._render_numbered("구분|수평 이동\n사례|•회사에 다니던 사람이 공인 중개사가 됨.•자동차 회사에서 부장을 하던 사람이 자리를 옮김.")
    assert any(ln.startswith("⠀⠀⠸⠲⠀⠚⠽⠇⠝⠀") for ln in out)      # gold 사회문화 p0112 37행 `  • 회사에 `
    assert any(ln.startswith("⠀⠀⠸⠲⠀⠨⠊⠿⠰⠣⠀") for ln in out)    # 40행 `  • 자동차 `
