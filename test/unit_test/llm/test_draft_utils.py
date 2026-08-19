import pytest
"""draft_utils — 점역사주 태그 포장 + 방식-라벨 제거(프리필 방식 채택 후)."""
from app.ai.llm.draft_utils import ensure_tn_prefix, parse_labeled_drafts


class TestEnsureTnPrefix:
    def test_방식라벨_제거(self):
        # 모델이 본문 앞에 붙이는 방식 이름은 점자에 안 찍히게 제거
        assert ensure_tn_prefix("상황 중심: 원 안에 삼각형") == "<!주>원 안에 삼각형<!/주>"
        assert ensure_tn_prefix("[점역사주] 위치 중심: 칠판 앞") == "<!주>칠판 앞<!/주>"
        assert ensure_tn_prefix("요약 중심: 수업 장면").endswith("수업 장면<!/주>")
        assert "대사 중심" not in ensure_tn_prefix("대사 중심: 선생님 안녕")

    def test_유형라벨_보존(self):
        # 그림:/만화: 등 유형 라벨은 방식 라벨이 아니므로 보존
        assert "그림: 교실" in ensure_tn_prefix("그림: 교실 수업")
        assert "만화: 선생님" in ensure_tn_prefix("만화: 선생님 등장")

    def test_빈입력(self):
        assert ensure_tn_prefix("") == ""
        assert ensure_tn_prefix("요약:") == ""   # 라벨만 있으면 빈 결과


class TestParseLabeledDrafts:
    def test_프리필_3안_파싱_라벨제거(self):
        raw = ("[방식1] [점역사주] 상황 중심: 원 안에 삼각형\n"
               "[방식2] [점역사주] 위치 중심: 삼각형은 원 안에\n"
               "[방식3] [점역사주] 요약: 원과 삼각형")
        methods = [("narrative", "상황 중심"), ("narrative", "위치 중심"), ("narrative", "요약")]
        ds = parse_labeled_drafts(raw, methods)
        assert len(ds) == 3
        assert ds[0].text == "<!주>원 안에 삼각형<!/주>"
        assert ds[2].text == "<!주>원과 삼각형<!/주>"
        assert len({d.text for d in ds}) == 3   # 세 초안 서로 다름


class TestWrapStyleSwitch:
    """시각 초안 포장 A/B — 주표(tn, 기본) vs 글상자(box). 원장 C-02 축.

    평가 실측(LLM-켬 12쪽): 우리 주표 9개 중 3개(33%)를 gold는 같은 내용의 **본문**으로
    낸다. 내용은 필요한데 포장만 다르다. 규칙 경로(`visual_drafts`)와 **같은 스위치**를
    읽어야 한 번의 A/B로 두 경로를 함께 본다 — 이 테스트가 그 정합을 묶는다.
    """

    @pytest.fixture(autouse=True)
    def _restore(self):
        """⚠ reload는 모듈 전역을 바꾼다 — 끝나면 기본값으로 되돌려야 다른 테스트가 안 샌다."""
        yield
        import importlib, os
        os.environ.pop("VISUAL_WRAP_STYLE", None)
        from app.ai.llm import draft_utils, visual_drafts
        importlib.reload(draft_utils); importlib.reload(visual_drafts)

    @staticmethod
    def _reload(monkeypatch, style: str):
        import importlib
        from app.ai.llm import draft_utils, visual_drafts
        monkeypatch.setenv("VISUAL_WRAP_STYLE", style)
        return importlib.reload(draft_utils), importlib.reload(visual_drafts)

    def test_기본은_주표(self, monkeypatch) -> None:
        d, v = self._reload(monkeypatch, "tn")
        assert d.ensure_tn_prefix("그래프: 설명").startswith("<!주>")
        assert v._tn("그래프: 설명").startswith("<!주>")

    def test_box면_두_경로_모두_글상자(self, monkeypatch) -> None:
        d, v = self._reload(monkeypatch, "box")
        for out in (d.ensure_tn_prefix("그래프: 설명"), v._tn("그래프: 설명")):
            assert out.startswith("<!상자>") and out.endswith("<!/상자끝>")
            assert "점역자주" not in out

    def test_전환해도_내용은_보존된다(self, monkeypatch) -> None:
        d, _ = self._reload(monkeypatch, "box")
        assert "카드 1: 기능론" in d.ensure_tn_prefix("카드 1: 기능론")


class TestAutoWrapRule:
    """auto 포장 — 전사(글상자)와 서술(주표)을 초안 모양으로 가른다. 원장 C-02.

    gold는 **둘 다 쓴다**(평가 실측 12쪽: gold 주표 888셀 · 테두리 33줄). 전면 전환은
    한쪽 오차를 다른 쪽 오차로 바꿀 뿐이다 — box 전면 전환 시 CER 62.8% → 62.2%.
      · 원문에 글로 있는 것(카드·보기 나열) → 글상자 본문 (사회문화 p147)
      · 그림을 말로 푼 것(그래프 추세·장치 묘사) → 주표
    """

    @pytest.fixture(autouse=True)
    def _auto(self, monkeypatch):
        import importlib
        from app.ai.llm import draft_utils
        monkeypatch.setenv("VISUAL_WRAP_STYLE", "auto")
        self.d = importlib.reload(draft_utils)
        yield
        import os
        os.environ.pop("VISUAL_WRAP_STYLE", None)
        importlib.reload(draft_utils)

    @pytest.mark.parametrize("text", [
        "그래프: 관점 비교 / 카드 1: 기능론 / 카드 2: 갈등론",
        "표: 항목 / ① 자유 / ② 평등 / ③ 박애",
        "그림: 단계\n1. 준비\n2. 실행\n3. 정리",
    ])
    def test_나열은_글상자(self, text: str) -> None:
        assert self.d.ensure_tn_prefix(text).startswith("<!상자>")

    @pytest.mark.parametrize("text", [
        "그래프: 가로축은 연도, 세로축은 인구수이며 2010년 이후 완만히 증가한다.",
        "사진: 광화문 앞 시위 장면",
        "그림: 실험 장치가 왼쪽에 놓여 있고 오른쪽으로 관이 이어진다.",
    ])
    def test_서술은_주표(self, text: str) -> None:
        assert self.d.ensure_tn_prefix(text).startswith("<!주>")

    def test_항목이_하나뿐이면_서술로_본다(self) -> None:
        """한 항목은 나열이 아니다 — 오검출을 막는 하한."""
        assert self.d.ensure_tn_prefix("그림: ① 자유만 표시됨").startswith("<!주>")


# ── 짧은 제목 잘림 (2026-08-19) ────────────────────────────────────────────
# 문장 경계가 없으면 limit자에서 기계적으로 잘리고 말줄임표가 붙었다. 캡셔너가 개조식으로
# 쓴 설명(`- 터번 형태의 두건 착용 - 긴 수염`)은 마침표가 없어 전부 걸렸다.
# 실측 캡션 13,393개 중 7,241개(54.1%)가 말줄임표로 끝났다.
class TestShortenNoEllipsis:
    def test_문장_경계가_없어도_말줄임표를_안_남긴다(self):
        from app.ai.llm.visual_drafts import _shorten
        out = _shorten("그림: 고대 철학자 또는 현자의 초상화(판화) - 터번 형태의 두건 착용 "
                       "- 긴 수염 - 망토 형태의 옷 착용")
        assert not out.endswith("…"), out
        assert out.endswith("두건 착용") or "-" not in out[-3:], out

    def test_항목_경계에서_온전히_끊는다(self):
        from app.ai.llm.visual_drafts import _shorten
        out = _shorten("만화: 중세 십자군 기사 - 전체: 사슬갑옷 두건, 십자무늬 튜닉, "
                       "큰 방패, 장검을 들고 서 있다")
        assert not out.endswith("…") and not out.endswith("-"), out

    def test_첫_문장_경계가_있으면_그쪽이_우선이다(self):
        from app.ai.llm.visual_drafts import _shorten
        out = _shorten("첫 문장은 여기서 끝난다. 둘째 문장은 아주 길게 이어진다 "
                       "어쩌고 저쩌고 그리고 또 계속 이어진다 한참 더.")
        assert out == "첫 문장은 여기서 끝난다.", out

    def test_첫_줄이_제목이면_그대로_쓴다(self):
        from app.ai.llm.visual_drafts import _shorten
        out = _shorten("첫 줄이 제목이다\n둘째 줄은 데이터 전체: 7.6% 1~2세: 6.8% 3~4세: 5.1%")
        assert out == "첫 줄이 제목이다", out

    def test_짧은_인쇄_캡션은_그대로_둔다(self):
        from app.ai.llm.visual_drafts import _shorten
        assert _shorten("짧은 인쇄 캡션") == "짧은 인쇄 캡션"
