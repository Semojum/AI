"""개인 점역 기본값 — 기획서 T3 §점역 기본 설정 계약 회귀.

기획서가 AI 소관으로 못 박은 것: "항목 목록은 AI가 스키마로 줍니다".
스키마가 조용히 바뀌면 BE 설정 화면이 어긋나고, 배선 표시가 거짓이면 설정 화면만
만들어 놓고 아무 일도 안 일어난다.
"""
import pytest

from app.ai.braille import constants as C
from app.ai.braille.nested_block import box_narrative
from app.ai.llm.visual_drafts import omission_draft
from app.core import braille_settings as bs


@pytest.fixture(autouse=True)
def _reset():
    bs.set_current(bs.Settings())
    yield
    bs.set_current(bs.Settings())


class TestSchema:
    def test_기획서_7항목이_다_있다(self):
        keys = {i["key"] for i in bs.schema_for_be()}
        assert keys == {"page_rows", "page_cols",      # 면 규격
                        "page_line",                   # 페이지행
                        "footer_format",               # 꼬리말 형식
                        "default_mode",                # 기본 변환 모드
                        "box_borders",                 # 표·글상자 테두리
                        "visual_omission_text",        # 그림 생략 표시
                        "tn_start_col"}                # 점역자 주 시작

    def test_기본값이_규정과_같다(self):
        """BBPG 1장1절3: 가로 32칸 · 세로 26줄."""
        assert bs.get("page_rows") == C.ROWS == 26
        assert bs.get("page_cols") == C.COLS == 32

    def test_배선_표시가_사실이어야_한다(self):
        """`wired`는 BE에 넘기는 약속이다. 안 된 걸 됐다고 하면 안 된다."""
        w = {i["key"]: i["wired"] for i in bs.schema_for_be()}
        assert w["box_borders"] and w["visual_omission_text"] and w["default_mode"]
        # 아직 안 된 것들 — 배선하면 이 단언을 뒤집고 스키마도 같이 고칠 것
        assert not w["page_rows"] and not w["page_cols"]
        assert not w["page_line"] and not w["footer_format"] and not w["tn_start_col"]

    def test_enum은_선택지를_준다(self):
        for i in bs.schema_for_be():
            if i["type"] == "enum":
                assert i["choices"], i["key"]
                assert i["default"] in {c[0] for c in i["choices"]}, i["key"]


class TestValidation:
    """설정 하나 때문에 점역이 멈추면 안 된다 — 나쁜 값은 조용히 버린다."""

    def test_범위_밖은_기본값(self):
        s = bs.Settings.from_dict({"page_rows": 999})
        assert s.get("page_rows") == C.ROWS

    def test_모르는_키는_무시(self):
        assert bs.Settings.from_dict({"없는키": 1}).get("page_rows") == C.ROWS

    def test_모르는_enum값은_기본값(self):
        assert bs.Settings.from_dict({"page_line": "이상"}).get("page_line") == "every"

    def test_None이나_빈_dict도_안전(self):
        for d in (None, {}):
            assert bs.Settings.from_dict(d).get("box_borders") is True

    def test_모르는_키_조회는_에러(self):
        """오타를 조용히 기본값으로 넘기면 배선 버그를 못 잡는다."""
        with pytest.raises(KeyError):
            bs.get("오타난키")


class TestWiring:
    """배선했다고 표시한 항목은 **실제로 출력을 바꿔야 한다.**"""

    def test_그림_생략_문구를_끌_수_있다(self):
        assert "생략" in omission_draft("그림").text
        bs.set_current(bs.Settings.from_dict({"visual_omission_text": "blank"}))
        assert omission_draft("그림").text == ""

    def test_테두리를_끌_수_있다(self):
        blocks = [{"label": "그래프", "description": "막대"}]
        assert "<!상자>" in box_narrative(blocks)
        bs.set_current(bs.Settings.from_dict({"box_borders": False}))
        out = box_narrative(blocks)
        assert "<!상자>" not in out and "<!상자끝>" not in out
        assert "그래프: 막대" in out, "테두리만 빠지고 내용은 남아야 한다"


class TestRequestPath:
    def test_proto_settings가_PageTask로_들어온다(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))
        import braille_service_pb2 as pb

        from app.schemas.task import PageTask
        req = pb.BrailleRequest(job_id="j", page_no=1, mode="c")
        req.settings["visual_omission_text"] = "blank"
        assert PageTask.from_proto(req).settings == {"visual_omission_text": "blank"}

    def test_설정_없는_요청도_동작한다(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))
        import braille_service_pb2 as pb

        from app.schemas.task import PageTask
        t = PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="c"))
        assert t.settings == {}
        assert bs.Settings.from_dict(t.settings).get("box_borders") is True
