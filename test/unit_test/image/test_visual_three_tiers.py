"""분량 세 단 — 간추린 설명 / 설명 / 자세한 설명 (2026-09-09 대표 결재, #808).

세 단은 **같은 재료에서 덜어 내기만** 한다. 그래서 지어낼 자리가 구조적으로 없다:

    캡션 ─┬─ [12] 자세한 설명  전부
          ├─ [ 2] 설명        머리줄 + 부분(들여쓰기 0)   ← 기본 선택
          └─ [11] 간추린 설명  머리줄

가르는 자는 **캡션 줄의 들여쓰기**다(`caption_outline` 의 level). 근거는 「점자 자료
제작 지침」 §6.1.4(4) L3011-3012 "전체 윤곽을 포괄적으로 설명한 다음 **부분을 나누어
단계적으로** 설명한다" 와 같은 조 (2) L3009 "핵심 내용 전달", (1) L3008 "적은 수의 단어".

★ 2026-09-07 에 `설명(자세히)` 를 만들었다 없앤 전례가 있다 — 그때는 LLM 에게 더 쓰라고
  시켜서 이름과 내용이 거꾸로 됐다('설명' 4줄 vs '자세히' 1줄, 그마저 캡션에 없는 말).
  그래서 이 파일은 **길이가 실제로 갈리는지**와 **글자가 캡션에 있는지**를 같이 본다.
"""
from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from app.ai.llm.image_opt import ImageOpt
from app.ai.llm.visual_drafts import DESC_OPTION, DETAIL_OPTION, GIST_OPTION
from app.schemas.content import ExtractedContent

_TAG = re.compile(r"<!/?[^>]*>")

# 세부 줄(두 칸 들여쓰기)이 있는 캡션. 캡셔너 프롬프트가 이 꼴을 내도록 지시한다.
_CAP = (
    "그림: 물의 순환\n"
    "증발: 바다에서 대기로 올라간다\n"
    "  바다 표면에 위쪽 화살표, 이름표 '증발'\n"
    "응결: 대기 중 수증기가 구름이 된다\n"
    "강수: 구름에서 비가 내린다\n"
    "  비 화살표 아래쪽, 이름표 '강수'"
)


def _drafts(caption: str):
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text=caption, structure={})
    out = asyncio.run(ImageOpt().optimize([ext], "ZERO"))[0]
    return {d.option: _TAG.sub("", d.text) for d in out.drafts}, out


def _lines(t: str) -> list[str]:
    return [l for l in t.split("\n") if l.strip()]


class TestThreeTiers:
    def test_세_단의_길이가_실제로_갈린다(self):
        d, _ = _drafts(_CAP)
        gist, desc, detail = d[GIST_OPTION], d[DESC_OPTION], d[DETAIL_OPTION]
        assert len(_lines(gist)) < len(_lines(desc)) < len(_lines(detail)), (
            [len(_lines(x)) for x in (gist, desc, detail)])
        assert len(gist) < len(desc) < len(detail)

    def test_기본_선택은_그대로_설명이다(self):
        _, out = _drafts(_CAP)
        assert out.drafts[out.selected_idx].option == DESC_OPTION

    def test_자세한_설명은_캡션에_있는_글자뿐이다(self):
        """지어낸 말이 한 줄도 없어야 한다 — `_outline_text_indents` 가 전사만 하므로."""
        d, _ = _drafts(_CAP)
        flat = re.sub(r"\s+", "", _CAP)
        for line in _lines(d[DETAIL_OPTION]):
            bare = re.sub(r"^(그림|사진|도표|그래프|만화)[:：]", "", re.sub(r"\s+", "", line))
            assert bare in flat, line

    def test_세부_줄이_없으면_자세한_설명을_안_낸다(self):
        """[2]와 같은 글이 피커에 두 번 서면 안 된다."""
        flat = "그림: 물의 순환\n증발\n응결\n강수"
        d, _ = _drafts(flat)
        assert DETAIL_OPTION not in d

    def test_호출부가_준_위계는_기본_안에서_안_걷힌다(self):
        """`struct_outline` 의 level 은 §6.4·§5.3 전사 위계지 '세부' 표시가 아니다.

        차트 `data_points` 를 걷어 내면 `2020: 980권` 같은 값 줄이 기본 안에서 사라진다.
        """
        from app.ai.llm.chart_graph_opt import ChartGraphOpt
        st = {"chart_subtype": "bar", "title": "연도별 발행 권수",
              "axes": {"x": {"label": "연도", "unit": ""}, "y": {"label": "권수", "unit": "권"}},
              "data_points": [{"label": "2020", "value": 980}, {"label": "2021", "value": 1100}],
              "caption_src": "연도별 발행 권수 막대그래프."}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
        out = asyncio.run(ChartGraphOpt().optimize([ext], "ZERO"))[0]
        text = _TAG.sub("", out.drafts[out.selected_idx].text)
        assert "2020: 980권" in text and "2021: 1100권" in text, text

    def test_본문이_전부_들여쓰기면_기본_안이_안_쪼그라든다(self):
        """캡셔너가 본문을 통째로 들여쓰면 들여쓰기는 '세부'가 아니라 목록 장식이다.

        안 걸러 내면 [2] 가 머리줄 하나로 남는다(62건 표본에서 1건 실측).
        """
        cap = ("그림: 염색체 쌍 세 개가 크기별로 놓여 있다.\n"
               "  큰 염색체 쌍: 두 개가 붙어 있다.\n"
               "  중간 염색체 쌍: 두 개가 붙어 있다.\n"
               "  작은 염색체 쌍: 두 개가 붙어 있다.")
        d, _ = _drafts(cap)
        assert len(_lines(d[DESC_OPTION])) == 4, d[DESC_OPTION]
        assert DETAIL_OPTION not in d          # 덜 것이 없으니 같은 글을 두 번 세우지 않는다
