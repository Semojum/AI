"""mode b에서 `<!표>` 구조 태그가 표로 나가는지 회귀.

`<!표>`/`<!행>`/`<!칸>`을 아는 것은 `table_braille`뿐이다. mode b가 이걸 텍스트 체인에
태우면 translator가 미지 태그로 지워 **셀이 한 줄로 붙은 채** 나간다 — 점역사는 표가
있었다는 사실조차 알 수 없다. 빈 결과보다 나쁘다(정상 문단인 척한다).

여기서 검증하는 것은 세그먼트 분할과 라우팅이다. 표 조판 자체(격자 테두리·행 구분선)는
`test/unit_test/table/`의 몫이라 중복해서 재지 않는다.
"""
import pytest

from app.core.pipeline import _mode_b_segments


class TestSegments:
    def test_표_블록은_한_요소로_묶인다(self):
        src = "<!표><!행><!칸>a<!/칸><!/행>\n<!행><!칸>b<!/칸><!/행><!/표>"
        segs = _mode_b_segments(src)
        assert len(segs) == 1, "여러 줄에 걸친 표가 줄 단위로 쪼개졌다"
        assert segs[0][1] == "table"
        assert segs[0][2] == src

    def test_표_앞뒤_본문은_줄_단위_text(self):
        src = "앞 문장\n<!표><!행><!칸>a<!/칸><!/행><!/표>\n뒤 문장"
        assert [(s[0], s[1]) for s in _mode_b_segments(src)] == [
            (1, "text"), (2, "table"), (3, "text")]

    def test_빈_줄은_요소를_안_만들고_번호만_건넌다(self):
        # 2026-08-06 규약: 문단 구분은 빈 줄이 아니라 들여쓰기다. 번호는 BE가 원문
        # 어디였는지 되짚는 열쇠라 건너뛴 채로 남긴다.
        assert [s[0] for s in _mode_b_segments("첫 줄\n\n\n넷째 줄")] == [1, 4]

    def test_표가_없으면_종전과_같다(self):
        assert _mode_b_segments("한 줄\n두 줄") == [(1, "text", "한 줄"), (2, "text", "두 줄")]

    def test_표_여러_개(self):
        src = ("<!표><!행><!칸>a<!/칸><!/행><!/표>\n"
               "사이 문장\n"
               "<!표><!행><!칸>b<!/칸><!/행><!/표>")
        assert [s[1] for s in _mode_b_segments(src)] == ["table", "text", "table"]


class TestCellCloseTag:
    """손으로 쓴 입력·BE txt는 `<!칸>`을 쌍으로 적는다 — 닫는 쪽을 셀 내용으로 세면 안 된다."""

    @pytest.mark.parametrize("row,expected", [
        ("<!행><!칸>이름<!/칸><!칸>점수<!/칸><!/행>", [["이름", "점수"]]),   # 쌍
        ("<!행><!칸>이름<!칸>점수<!/행>", [["이름", "점수"]]),               # 여는 쪽만
        ("<!행><!칸>이름<!/칸><!칸><!/칸><!/행>", [["이름", ""]]),           # 빈 셀 보존
    ])
    def test_칸_구분(self, row, expected):
        from app.ai.braille.table_braille import parse_table_tags
        assert parse_table_tags(f"<!표>{row}<!/표>") == expected


class TestRenderMode:
    """`<!표>` 태그로 직접 들어오면 열 수를 태그에서 세야 한다 — HTML도 파이프도 아니다."""

    @pytest.mark.parametrize("cols,expected", [(2, "linear"), (3, "table_grid")])
    def test_열_수로_갈린다(self, cols, expected):
        from app.ai.llm.table_opt import _infer_render_mode
        cells = "".join(f"<!칸>c{i}<!/칸>" for i in range(cols))
        assert _infer_render_mode(None, f"<!표><!행>{cells}<!/행><!/표>") == expected

    def test_2열_스위치_기본은_풀어쓰기(self, monkeypatch):
        """기본값은 종전 그대로 `linear` 다 — 스위치를 켜야 격자로 간다(원장 C-30).

        2026-08-29 실측: 우리가 `linear` 를 고른 표 167개 중 **166개가 "2열이라서"** 이고,
        그 쪽에서 gold 는 행 구분선을 81개 쓰는데 우리는 23개뿐이다(= gold 는 격자를 쓴다).
        근거는 섰지만 표 배치는 초안 넷 중 무엇을 고르냐를 바꾸는 축이라 기본을 안 뒤집는다.
        """
        from app.ai.llm.table_opt import _infer_render_mode, two_col_mode
        two = "<!칸>a<!/칸><!칸>b<!/칸>"
        tbl = f"<!표><!행>{two}<!/행><!/표>"
        monkeypatch.delenv("TABLE_TWO_COL", raising=False)
        assert two_col_mode() == "linear"
        assert _infer_render_mode(None, tbl) == "linear"
        monkeypatch.setenv("TABLE_TWO_COL", "grid")
        assert two_col_mode() == "table_grid"
        assert _infer_render_mode(None, tbl) == "table_grid"

    def test_3열은_스위치와_무관하게_격자(self, monkeypatch):
        """스위치는 **2열에만** 건다. 3열 이상은 이미 격자라 안 건드린다."""
        from app.ai.llm.table_opt import _infer_render_mode
        three = "".join(f"<!칸>c{i}<!/칸>" for i in range(3))
        tbl = f"<!표><!행>{three}<!/행><!/표>"
        for v in (None, "grid"):
            if v is None:
                monkeypatch.delenv("TABLE_TWO_COL", raising=False)
            else:
                monkeypatch.setenv("TABLE_TWO_COL", v)
            assert _infer_render_mode(None, tbl) == "table_grid"

    def test_태그가_없으면_종전_추론(self):
        from app.ai.llm.table_opt import _infer_render_mode
        assert _infer_render_mode(None, "그냥 문장이다") == "narrative"
