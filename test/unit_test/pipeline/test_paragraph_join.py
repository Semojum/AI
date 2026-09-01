"""인쇄면 줄바꿈 잇기 — NLD §1.2.1 어절 단위 줄바꿈.

MinerU/OCR 추출은 인쇄면 한 줄이 한 줄이라 문단 가운데 줄바꿈이 남는다. 그대로 점역하면
어절이 인쇄면 줄 끝에서 갈린다(`총 5개` / `의 문항이`). 실측 OCR 텍스트 요소의 35.4%.
"""
import pytest

from app.core.pipeline import _join_wrapped_lines as join


def test_어절_가운데서_끊긴_줄은_붙여_잇는다():
    assert join("듣기는 4개의 대본에서 총 5개\n의 문항이 출제된다.") == \
        "듣기는 4개의 대본에서 총 5개의 문항이 출제된다."


def test_어절_경계에서_끊긴_줄은_띄어_잇는다():
    got = join("05 다음 유적과 유물을 남긴 고대 문명에 대한 옳은 설명을\n<보기>에서 고른 것은?")
    assert got == "05 다음 유적과 유물을 남긴 고대 문명에 대한 옳은 설명을 <보기>에서 고른 것은?"


def test_다음_줄_첫_어절이_들어갔으면_내용상_줄바꿈으로_보존한다():
    # 첫 줄이 단 폭(25)의 절반도 안 차는데 줄을 바꿨다 = 폭에 밀린 게 아니라 내용이다.
    src = "제목처럼 짧은 줄\n그 뒤로 이어지는 아주 긴 본문 줄이 여기\n또 하나의 긴 본문 줄"
    assert join(src).startswith("제목처럼 짧은 줄\n")


def test_어절_가운데_갈림은_들어갔더라도_잇는다():
    # `5개` + `의` — 폭에 여유가 있어도 어절 가운데 줄바꿈은 어떤 조판에서도 내용이 아니다.
    assert "5개의" in join("듣기는 4개의 대본에서 총 5개\n의 문항이 출제된다 여기까지가 한 줄")


def test_좁고_들쭉날쭉한_블록은_보존한다():
    poem = "산에는 꽃 피네\n꽃이 피네\n갈 봄 여름 없이\n꽃이 피네"
    assert join(poem) == poem


def test_번호_목록은_잇지_않는다():
    src = "다음 중 옳은 것을 모두 고르시오 여기까지가 첫 줄\n① 첫째 항목이며 길이가 비슷한 줄\n② 둘째 항목이며 길이가 비슷함"
    assert join(src) == src


def test_빈_줄은_문단_경계라_유지된다():
    src = "앞 문단의 첫 줄이고 길이가 비슷하다\n앞 문단의 둘째 줄이고 길이 비슷\n\n뒤 문단"
    out = join(src)
    assert out.count("\n\n") == 1 and "\n" not in out.split("\n\n")[0]


@pytest.mark.parametrize("src", ["", "한 줄뿐", "끝\n"])
def test_이을_것이_없으면_그대로(src):
    assert join(src) == src


class TestEdgeHeaderSuppression:
    """지면 가장자리 머리글 억제 — 도서명 배너만 지우고 나머지는 살린다."""

    BAND = (100.0, 1400.0, 1300.0)          # (top, bot, height)
    EDGE = [0, 1380, 500, 1400]             # 지면 아래 끝

    def test_도서명_배너를_억제한다(self) -> None:
        from app.core.pipeline import _is_edge_header

        assert _is_edge_header("2 2027학년도 EBS 수능특강 문학", self.EDGE, self.BAND)
        assert _is_edge_header("정답과 해설  19", self.EDGE, self.BAND)

    def test_본문_상호참조는_살린다(self) -> None:
        """`정답과 해설 125쪽`은 머리글이 아니라 본문 참조다(실측 손해 1건이 이것)."""
        from app.core.pipeline import _is_edge_header

        assert not _is_edge_header("정답과 해설 125쪽", self.EDGE, self.BAND)

    def test_글상자가_붙으면_살린다(self) -> None:
        """통째로 지우면 테두리를 잃는다."""
        from app.core.pipeline import _is_edge_header

        assert not _is_edge_header("<!상자>정답과 해설 21<!/상자>", self.EDGE, self.BAND)

    def test_출처_표기는_살린다(self) -> None:
        """정답본이 `2025학년도 수능`·`1회`를 출처로 살린다(실측 손해 3건이 이것)."""
        from app.core.pipeline import _is_edge_header

        assert not _is_edge_header("2025학년도 수능", self.EDGE, self.BAND)
        assert not _is_edge_header("1회", self.EDGE, self.BAND)

    def test_지면_가운데는_안_건드린다(self) -> None:
        from app.core.pipeline import _is_edge_header

        assert not _is_edge_header("정답과 해설  19", [0, 700, 500, 720], self.BAND)
