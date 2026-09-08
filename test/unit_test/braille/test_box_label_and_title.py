"""글상자 제목 점형 회귀 (#732 C).

글상자 제목 `<보기>` 가 부등호(⠔⠔…⠢⠢)로 나가, 같은 쪽 본문의 〈보기〉(⠐⠶…⠶⠂)와
두 모양으로 갈렸다. 실물 mode b 실행에서 재현됐다(`temp/e2e/판정_0908.md` C절).
표지 검출(B)·mode b 상자 경계(D)는 `test/unit_test/pipeline/test_mode_b_box.py` 몫이다.

규정 근거:
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

OPEN, CLOSE = "⠐⠶", "⠶⠂"      # 〈 · 〉
BOGI = "⠘⠥⠈⠕"                 # 보기


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
