"""도표 세분류 배선 회귀 — §6.6 골격 8종이 **실제로 선다** (#784).

## 왜 이 파일이 있나

2026-09-08 실측에서 `diagram_opt._ASSEMBLERS` 의 §6.6 골격 8종이 **한 번도 안 돌았다**
(`temp/label46/흔들림_0908.md` §5 — 도표 크롭 4장 × 5회에서 `visual_subtype` 20/20 빈칸).

원인은 구조였다. 세분류를 **사람이 읽는 캡션 문장에서 정규식으로 되읽었다**. 그래서 캡션
문안을 고칠 때마다 조용히 끊겼다 —

    captioner 프롬프트가 "종류 이름을 쓰지 마세요"        (#646, 09-07)
      → 써도 `_strip_dup_type_word` 가 뗀다               (#734, 09-08)
        → `_TYPE_WORD["diagram"]` 이 도표 → 그림
          → `subtype_from_caption` 이 찾을 낱말이 없다

**이틀 만에 끊겼는데 테스트가 하나도 안 울었다.** 그 구멍을 이 파일이 막는다.

## 이 파일이 지키는 두 가지

1. **§6.6 골격 8종이 한 번도 안 서면 실패한다** (`TestEverySkeletonStands`).
2. **캡션 문안에 유형어가 하나도 없어도 골격이 선다** (`TestSubtypeIsNotCaptionText`).
   캡션 프롬프트를 어떻게 고쳐도 이 검사는 안 끊긴다 — 세분류가 분류 콜에서 오기 때문이다.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from app.ai.captioning import classifier
from app.ai.llm import diagram_opt
from app.ai.llm.diagram_structure import (
    SUBTYPES, structure_from_caption, subtype_from_caption,
)
from app.ai.llm.diagram_opt import DiagramOpt
from app.schemas.content import ExtractedContent

# 「점자 자료 제작 지침」 §6.6 도표 — 조항과 값의 1:1 표.
# 원문(`braille-source/text/점자 자료 제작 지침_재추출.txt`) L3524 가 여덟을 열거하고
# L3526·3542·3640·3668·3722·3781·3818·3854 가 각각의 절이다.
# ★ 여기에 없는 낱말은 넣지 않는다 — 조항을 못 대는 값은 §6.6 밖 자료에 없는 골격을 씌운다.
_REG = {
    "concept_map": "6.6.1",    # 개념도  L3526
    "flowchart": "6.6.2",      # 흐름도  L3542
    "form": "6.6.3",           # 양식    L3640
    "family_tree": "6.6.4",    # 가계도  L3668
    "org_chart": "6.6.5",      # 조직도  L3722
    "timeline": "6.6.6",       # 연대표  L3781
    "screen_image": "6.6.7",   # 화면 이미지     L3818
    "slide": "6.6.8",          # 발표용 슬라이드 L3854
}

# 유형별 캡션 — **유형어를 한 낱말도 안 쓴다.** 오늘 캡셔너가 실제로 내는 모양이다
# (`_TYPE_WORD["diagram"]` = '그림', 프롬프트가 종류 이름 금지, `_strip_dup_type_word` 가 제거).
# 아래 `test_캡션만으로는_세분류가_안_나온다` 가 그 사실을 매번 확인한다.
_CAPTIONS = {
    "concept_map": "그림: 생물의 분류\n1. 생물\n1) 동물\n① 포유류\n1) 식물",
    "flowchart":   "그림: 정자 형성\n감수 1분열\n감수 2분열\n정자 4개",
    "form":        "그림: 도서 대출 신청\n이름\n학번\n대출 희망 도서",
    "family_tree": "그림: 유전 형질 조사\n1세대\n- 1: 정상 남자\n- 2: 발현 여자\n2세대\n- 3: 정상 여자",
    "org_chart":   "그림: 고려의 중앙 통치\n1. 국왕\n1) 중서문하성\n1) 상서성",
    "timeline":    "그림: 독립운동\n1919년 3·1 운동\n1920년 청산리 대첩\n1932년 윤봉길 의거",
    "screen_image": "그림: 국립중앙도서관 첫 화면\n도구 막대\n검색창\n로그인\n본문\n공지 사항",
    "slide":       "그림: 기후 변화 발표\n1. 원인\n1) 온실가스\n2. 대책",
}


class TestRegulationValues:
    """세분류 값 집합은 §6.6 이 정한 여덟이고, 코드 곳곳의 열쇠가 그것과 같아야 한다."""

    def test_여덟이고_조항이_있다(self):
        assert len(SUBTYPES) == 8
        assert set(SUBTYPES) == set(_REG), "§6.6 조항을 못 대는 값이 섞였다"

    def test_코드_열쇠가_전부_같다(self):
        # 하나라도 어긋나면 그 유형은 조립되거나 근거가 붙거나 이름이 뜨는 것 중
        # 하나를 잃는다. 조용히 잃지 않게 여기서 묶는다.
        assert set(diagram_opt._ASSEMBLERS) == set(SUBTYPES)
        assert set(diagram_opt._SUBTYPE_RULE) == set(SUBTYPES)
        assert set(diagram_opt._TYPE_LABEL) == set(SUBTYPES)

    def test_근거_조항이_규정_번호와_같다(self):
        for sub, clause in _REG.items():
            assert diagram_opt._SUBTYPE_RULE[sub] == f"NISE-{clause}", sub

    def test_세분류_프롬프트가_여덟을_다_말한다(self):
        """★ 프롬프트에서 한 유형을 빼면 그 골격은 다시는 안 선다 — 여기서 잡는다."""
        for sub, clause in _REG.items():
            assert sub in classifier._SUBTYPE_PROMPT, f"{sub} 를 세분류 프롬프트가 안 말한다"
            assert classifier._SUBTYPE_CLAUSE[sub] == clause, f"{sub} 의 조항이 다르다"

    def test_분류_프롬프트에는_세분류_어휘가_없다(self):
        """★ 라벨이 안 움직이는 **구조적 보장**이 여기 걸려 있다(#784).

        세분류 어휘를 `SYSTEM_PROMPT` 에 섞으면 라벨 판정이 딸려 움직인다 — 문안 세 판을
        4-6 표본 36크롭 × 3회로 재 보니 전부 4~6건이 갈렸고 만화 한 건이 세 판 모두
        `diagram timeline` 으로 끌려갔다. 이 모델은 `temperature` 를 거절해서
        (400 `deprecated for this model`) 그 움직임을 실측으로 걷어낼 수도 없다.
        그래서 두 프롬프트를 **한 자리에 두지 않는 것**을 검사로 못 박는다.
        """
        for sub in SUBTYPES:
            assert sub not in classifier.SYSTEM_PROMPT, (
                f"{sub} 가 분류 프롬프트에 섞였다 — 라벨이 움직인다")


class TestSubtypeResponseParsing:
    """세분류 콜 응답 → 하위유형. **분류 응답과 별개 경로**다."""

    @pytest.mark.parametrize("sub", SUBTYPES)
    def test_여덟_다_받는다(self, sub):
        assert classifier._parse_subtype(sub) == sub
        assert classifier._parse_subtype(f"diagram {sub}") == sub      # 캐시에 담기는 꼴

    def test_목록_밖_낱말은_안_받는다(self):
        # §6.6 에 조항이 없는 자료(지도·벤다이어그램)에 골격을 억지로 씌우지 않는다.
        for word in ("none", "map", "venn", "cross_section", ""):
            assert classifier._parse_subtype(word) == "", word


class TestEverySkeletonStands:
    """★ §6.6 골격 8종이 **하나도 안 서면 실패한다.**

    2026-09-08 이전에는 8종 전부가 0회였고 아무 테스트도 안 울었다.
    """

    @staticmethod
    def _run(sub: str):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               corrected_text=_CAPTIONS[sub], visual_subtype=sub)
        return asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]

    @pytest.mark.parametrize("sub", SUBTYPES)
    def test_골격이_선다(self, sub):
        out = self._run(sub)
        tags = [r.tag for r in out.rule_trail]
        assert any("골격 조립" in t for t in tags), (
            f"{sub}: §6.6 골격이 안 섰다(캡션 폴백으로 떨어졌다) — {tags}")
        assert out.rule_trail[0].rule_id == f"NISE-{_REG[sub]}", sub
        assert out.corrected_text.strip(), sub

    def test_여덟이_모두_선다(self):
        """유형별로 몇 개나 서는지 센다 — 하나라도 0이면 실패."""
        stood = [s for s in SUBTYPES
                 if any("골격 조립" in r.tag for r in self._run(s).rule_trail)]
        assert stood == list(SUBTYPES), f"안 선 유형: {set(SUBTYPES) - set(stood)}"


class TestSubtypeIsNotCaptionText:
    """★ 캡션 문안을 바꿔도 안 끊긴다 — 세분류가 캡션 글자에서 안 온다."""

    @pytest.mark.parametrize("sub", SUBTYPES)
    def test_캡션만으로는_세분류가_안_나온다(self, sub):
        """이 캡션들에는 유형어가 없다. 옛 경로였다면 여기서 전부 빈칸이었다."""
        assert subtype_from_caption(_CAPTIONS[sub]) == "", (
            f"{sub}: 시험 캡션에 유형어가 섞였다 — 검사가 옛 경로를 재고 있다")

    @pytest.mark.parametrize("sub", SUBTYPES)
    def test_그래도_골격이_선다(self, sub):
        """유형어가 없는 캡션 + 분류 콜이 준 세분류 → §6.6 골격."""
        st = structure_from_caption(_CAPTIONS[sub], sub)
        assert st and st["subtype"] == sub, sub
        assert diagram_opt._ASSEMBLERS[sub][1](st), f"{sub}: 골격 재료가 안 만들어졌다"

    def test_분류_응답부터_골격까지_한_사슬(self, monkeypatch, tmp_path):
        """분류 콜 응답 → 경계 JSON `visual_subtype` → §6.6 골격. 캡션은 유형어가 없다."""
        import app.ai.builder.result_builder as rb

        monkeypatch.chdir(tmp_path)
        cap = _CAPTIONS["org_chart"]
        monkeypatch.setattr(rb, "classify_with_confidence",
                            lambda p: ("diagram", 0.9, "org_chart"))
        monkeypatch.setattr(rb, "caption", lambda p, t, context="": cap)
        monkeypatch.setattr(rb.Path, "exists", lambda self: True)
        el = {"element_id": "e1", "type": "image", "image_path": "/tmp/none.png",
              "bbox": [100, 100, 500, 400], "bbox_px": [200, 200, 1000, 800],
              "page_no": 1, "job_id": "t_chain"}
        entry = rb.build([el], "t_chain", 1, "OCR")["elements"][0]
        assert entry["visual_subtype"] == "org_chart"

        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               corrected_text=entry["content"],
                               visual_subtype=entry["visual_subtype"])
        out = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert out.rule_trail[0].rule_id == "NISE-6.6.5"     # §6.6.5 조직도
        assert "국왕" in out.corrected_text


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
