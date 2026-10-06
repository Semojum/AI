"""홑화살괄호 줄 넘김 역맵 회귀 가드 (2026-09-06, 이슈 #584 · 원장 R-52).

규정 문장부호표: 〈 = ⠐⠶ · 〉 = ⠶⠂ (「한국 점자 규정」 재추출본 2191~2195행).
닫는 표의 첫 셀 ⠶ 가 **종성 ㅇ과 같은 셀**이라 탐욕 매칭이 앞 음절에 붙여 먹고
남은 ⠂ 가 쉼표로 떨어진다 — `추이〉` → `추잉,` · `결과〉` → `결광,`.

종전 가드는 `_decode_line` 안에 있어 **같은 줄**의 짝만 봤다. 점자책은 32칸 조판이라
제목이 두세 줄에 걸친다. 전권 18,892쪽 실측: 짝 4,886 중 **367 이 줄을 넘는다**.
"""


class TestAnglePairLineWrap:
    def test_줄을_넘는_짝이_화살괄호로_읽힌다(self):
        """〈학습 활동을 수행한⏎결과〉 — 종전 출력 `결광,`(문학 p0118 실물)."""
        from app.utils.braille_back import decode
        got = decode("⠐⠶⠚⠁⠠⠪⠃⠀\n⠚⠧⠂⠊⠿⠶⠂")
        assert got.startswith("〈") and got.endswith("〉"), got
        assert "활동" in got and "," not in got, got

    def test_한_줄_짝은_그대로(self):
        from app.utils.braille_back import decode
        assert decode("⠐⠶⠘⠥⠈⠕⠶⠂") == "〈보기〉"

    def test_짝_없는_닫는_셀은_받침_ㅇ_그대로(self):
        """여는 ⠐⠶ 가 없으면 화살괄호로 보지 않고 종전 판정(받침 ㅇ + 쉼표)을 유지한다.

        ⚠ 이 기대값은 **코퍼스 근거가 없는 대체 판정**이다. 전권 18,892쪽에서 짝 못 찾은 ⠶⠂ 는
        41건인데(2026-10-07 재셈, temp/n46/bk/angle_unpaired.py) **전부 집합 괄호 + 쉼표**다 —
        `7a71`(`{a},`) · `7;c71`(`{c},`) 꼴, MS-REF-007 · HS-REF-007 · EBS-E26-002 의 수식.
        받침 ㅇ + 쉼표도, 짝 잃은 〉 도 0건이다. 종전 docstring 의 "전부 받침 ㅇ + 쉼표" 는 틀렸다.
        그 41건은 지금 역점역이 `{a〉` · `{_낭,` 으로 깨뜨린다(집합 괄호 갈래, 따로 볼 거리).
        """
        from app.utils.braille_back import decode
        assert decode("⠈⠳⠈⠧⠶⠂") == "결광,"

    def test_너무_먼_짝은_안_잡는다(self):
        """길이 상한 240셀 — 실측 짝 내용은 최장 140셀이라 넉넉하다."""
        from app.utils.braille_back import decode
        far = "⠐⠶" + "⠫" * 300 + "⠈⠳⠈⠧⠶⠂"
        assert far[-6:] and decode(far).endswith("결광,")
