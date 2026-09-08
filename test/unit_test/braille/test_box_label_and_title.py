"""글상자 표지 검출·제목 점형 회귀 (#732).

세 가지를 한자리에서 잡는다. 셋 다 실물 mode b 실행에서 재현됐다(`temp/e2e/판정_0908.md` B·C·D).

B 자간 벌린 표지(`<보 기>`)가 태깅 후보로 안 잡혀 **LLM 호출조차 안 나갔다**(외부LLM 0회)
  → 테두리가 한 칸도 안 나갔다.
C 글상자 제목 `<보기>` 가 부등호(⠔⠔…⠢⠢)로 나가, 같은 쪽 본문의 〈보기〉(⠐⠶…⠶⠂)와
  두 모양으로 갈렸다.
D mode b 가 표지 줄을 제 요소로 떼는 바람에 태깅 LLM 이 그 줄만 감싸 상자가 늘 비었다.

규정 근거(C·B의 자간 붙임):
  「한국 점자 규정」 문장부호표 `한국 점자 규정_재추출.txt` 2186~2193행
      여는 홑화살괄호 `"7`=⠐⠶ · 닫는 홑화살괄호 `71`=⠶⠂
  「점자 도서 제작 지침」[예 1-11] `점자 도서 제작 지침_재추출.txt` 423~429행
      글상자 제목 `<보 기>` → ``=gggg`"7^u@o71`gggggggggggggggg=``
      = ⠿⠛⠛⠛⠛ ⠀ ⠐⠶보기⠶⠂ ⠀ ⠛…⠿ (자간은 붙여 적는다)
  같은 지침 [예 1-13] 458·464행 `<눈길>` → `"7cg@o171` 도 같은 꼴.
gold 실측(2027 코퍼스 18,892파일 전수): 위 테두리 제목에 '보기'가 든 946줄 중
  홑화살괄호 399 · 괄호 없는 맨몸 494 · 그 밖 53 · **부등호 0**.
  '보기'를 벌려 적은 제목(⠘⠥⠀⠈⠕) 도 **0**이다(붙임 946).
"""
from app.ai.braille.translator import translate_plain
from app.ai.llm.text_opt import _TAG_CANDIDATE_RE
from app.core.pipeline import _mode_b_segments

OPEN, CLOSE = "⠐⠶", "⠶⠂"      # 〈 · 〉
BOGI = "⠘⠥⠈⠕"                 # 보기


class TestB표지검출:
    def test_자간_벌린_표지도_태깅_후보다(self):
        assert _TAG_CANDIDATE_RE.search("<보기>")
        assert _TAG_CANDIDATE_RE.search("<보 기>"), "자간 조판 표지가 LLM 호출조차 못 받는다"
        assert _TAG_CANDIDATE_RE.search("[자 료 1]")

    def test_표지가_아닌_꺽쇠는_후보가_아니다(self):
        assert not _TAG_CANDIDATE_RE.search("x < 10 이고 y > 3 이다")


class TestC제목점형:
    def test_제목이_본문과_같은_홑화살괄호다(self):
        body = translate_plain("<보기>")
        title_line = translate_plain("<!상자><보기><!/상자>")
        assert body == OPEN + BOGI + CLOSE
        assert OPEN + BOGI + CLOSE in title_line, "제목이 부등호(⠔⠔…⠢⠢)로 나갔다"
        assert "⠔⠔" not in title_line and "⠢⠢" not in title_line

    def test_자간_벌린_제목은_붙여_적는다(self):
        # 지침 [예 1-11] 429행과 같은 줄이 나와야 한다.
        assert translate_plain("<!상자><보 기><!/상자>") == (
            "⠿" + "⠛" * 4 + "⠀" + OPEN + BOGI + CLOSE + "⠀" + "⠛" * 16 + "⠿")

    def test_진짜_띄어쓴_제목은_그대로_둔다(self):
        # `자료 1` 은 자간 조판이 아니라 낱말 사이 띄어쓰기다 — 붙이면 안 된다.
        assert "⠨⠐⠬⠀⠼⠁" in translate_plain("<!상자><자료 1><!/상자>")


class TestDmodeB상자경계:
    def test_표지_줄과_본문이_한_요소로_묶인다(self):
        src = "<보기>\n첫 줄이다.\n둘째 줄이다.\n\n5. <보기>의 ㄱ은?"
        segs = _mode_b_segments(src)
        assert segs[0] == (1, "text", "<보기>\n첫 줄이다.\n둘째 줄이다."), (
            "표지 줄이 제 요소로 떨어지면 태깅 LLM 이 그 줄만 감싸 상자가 빈다")
        assert segs[1] == (5, "text", "5. <보기>의 ㄱ은?")

    def test_표지_뒤에_조사가_붙으면_참조라_안_묶는다(self):
        src = "<보기>의 ㄱ에 대한 설명은?\n① 첫째다."
        assert [s[0] for s in _mode_b_segments(src)] == [1, 2]

    def test_표지_뒤가_빈_줄이면_안_묶는다(self):
        assert [s[2] for s in _mode_b_segments("<보기>\n\n딴 문단이다.")] == [
            "<보기>", "딴 문단이다."]

    def test_빈_줄_없는_원고가_통째로_한_요소가_되지_않는다(self):
        src = "<보기>\n" + "\n".join(f"{i}번째 줄이다." for i in range(60))
        segs = _mode_b_segments(src)
        assert segs[0][2].count("\n") + 1 == 31, "표지 + 30줄에서 끊겨야 한다"
        assert len(segs) == 31
