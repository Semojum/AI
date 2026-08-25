"""만화 대본 형식 회귀 — QA 2026-08-07 12·13·14번.

근거(모두 원문 대조):
  · 「제작 지침」§5.3.3(1) 장면 번호 5칸 / (2) 인물의 대화 3칸 / (3) 인물명과 대사는 쌍점 구분
  · BBPG 제3장 9)(1)② 컷과 컷 사이에는 빈 줄을 두지 않는다
  · BBPG [예 3-54] 정답 점자 역점역 = "학생: 선생님, 농업의 사회적 …" (쌍점 뒤 한 칸)
  · §6.3.4(3) 화자 불명은 '말풍선'
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.llm.cartoon_opt import CartoonOpt, _caption_items
from app.ai.llm.visual_drafts import _tn
from app.schemas.content import ExtractedContent

# 대표님 QA 실행분(job_260807160446 p2) 캡션 원문 형식 그대로 — 빈 줄·'대사:'·'흐름:' 포함.
_REAL = (
    "만화: 탄산 약수터에서 두 학생이 탄산 이온 확인 방법을 궁리하는 4컷 만화\n"
    "\n"
    "1컷: 남학생과 여학생이 약수터 앞에 도착\n"
    '대사: "이게 그 유명한 탄산 약수구나!"\n'
    "\n"
    "2컷: 여학생이 국자로 물을 떠서 마심\n"
    '대사: "톡 쏘는 맛이 날 것 같기도 하고!"\n'
    "\n"
    "흐름: 약수터 발견 → 맛으로 탄산 이온 추측 → 과학적 확인 방법 고민"
)

# 새 캡셔닝 프롬프트가 내도록 한 형식(§5.3 대본).
_SCRIPT = ("만화: 농업의 사회적 역할을 묻는 대화\n"
           "장면 1\n"
           "학생: 선생님, 농업의 사회적 역할이 무엇인가요?\n"
           "선생님: 사람이 살아가는 데 가장 중요한 먹거리를 제공해 주는 것이지.\n")


def _outline(caption: str) -> str:
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=caption)
    return asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0].corrected_text


class TestScriptFormat:
    def test_대사가_인물명_쌍점_형식으로_나온다(self):
        """QA 13번 — '(인물명): (대사)' 형식. BBPG 예3-54 정답 대조."""
        out = _outline(_SCRIPT)
        assert "학생: 선생님, 농업의 사회적 역할이 무엇인가요?" in out
        assert "선생님: 사람이 살아가는 데" in out

    def test_대사가_한_줄도_빠지지_않는다(self):
        """QA 12번 — 대사 누락 금지."""
        out = _outline(_REAL)
        assert "이게 그 유명한 탄산 약수구나!" in out
        assert "톡 쏘는 맛이 날 것 같기도 하고!" in out

    def test_화자_불명은_말풍선(self):
        """§6.3.4(3). 구 캡션의 '대사:' 머리말이 그대로 화자가 되면 안 된다."""
        out = _outline(_REAL)
        assert "말풍선: " in out
        assert "\n대사:" not in out and not out.startswith("대사:")

    def test_전체_재요약_줄은_버린다(self):
        """QA 13번 '그 이후에 그림을 전체적으로 또 설명 → 내용이 중복'."""
        assert "흐름:" not in _outline(_REAL)

    def test_빈_줄이_없다(self):
        """QA 14번 + BBPG 3장 9)(1)②."""
        out = _outline(_REAL)
        assert "\n\n" not in out
        assert all(line.strip() for line in out.splitlines())

    def test_들여쓰기가_규정_칸수이고_줄수와_맞는다(self):
        """§5.3.3(1) 장면 5칸 · (2) 대화 3칸. 그리고 line_indents는 줄마다 하나씩.

        ★ **값은 앞 빈칸 수다. 규정의 칸 번호가 아니다.**(2026-08-25 정정)
          "5칸에서 적는다" = 앞 빈칸 4 · "3칸에서 적는다" = 앞 빈칸 2.
          이 테스트가 5·3 을 그대로 박고 있어서 `_OUTLINE_BASE` 의 off-by-one 을
          열다섯 날 지켜 주고 있었다.
        """
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=_SCRIPT)
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))[0]
        lines = opt.corrected_text.splitlines()
        assert len(opt.line_indents) == len(lines)          # 종전엔 어긋났다(head 안 줄바꿈)
        got = dict(zip(lines, opt.line_indents))
        assert got["장면 1"] == 4        # §5.3.3(1) "5칸에서 적는다"
        assert got["학생: 선생님, 농업의 사회적 역할이 무엇인가요?"] == 2   # (2) "3칸"

    def test_제목이_두_번_나오지_않는다(self):
        """§5.3(1) 제목은 점역자주 머리줄 한 곳. QA 13번 중복."""
        out = _outline(_SCRIPT)
        assert out.count("농업의 사회적 역할을 묻는 대화") == 1

    def test_대본이_아니면_손대지_않는다(self):
        """줄글 캡션은 구 경로(§5.3.2 한 장면 설명)로 물러난다."""
        assert _caption_items("만화: 다섯 후보가 공약을 발표하는 장면") == ("", [])


class TestTnNoBlankLine:
    def test_점역자주는_논리_줄_하나로_접힌다(self):
        """QA 14번 근본 위치 — 캡션 34건 중 27건이 빈 줄을 갖고 있었다."""
        assert _tn("가\n\n나\n다") == "<!주>가 나 다<!/주>"
