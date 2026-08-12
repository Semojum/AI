"""제목 없는 글상자의 본문에 남은 상자 제목을 위 테두리로 올린다 (2026-08-10).

태깅 LLM이 상자 제목을 `<!상자>` 안에 넣을 때와 본문 줄로 남길 때가 갈린다. 원인은
MinerU 병합이다 — 제목이 별도 요소로 오면 승격되고, 첫 항목에 붙어 오면(`보기ㄱ. A는 …`)
LLM이 떼어 내 본문 끝줄로 민다. 실측 EBS-E26-001 p0118: 네 상자 중 **둘만 승격**됐고
정답은 넷 다 위 테두리에 제목을 박는다(지침 §2.1.6(1)②).

승격 후 위 테두리는 정답과 셀 단위로 같다:
    ⠿⠛⠛⠛⠛⠀⠘⠥⠈⠕⠀⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠿   (= 【보기】 상자 위 테두리)

⚠ "짧은 한 줄이면 제목"으로 일반화하지 않는다 — 같은 표본 004 p0118에서 글꼴 깨진 본문
첫 줄(`▵▵고교복`)이 걸리는데 정답은 그걸 승격하지 않는다. 정답에서 실제로 관측된 제목
낱말만 올린다(gold 2,917쪽 위 테두리 1,634건 실측).
"""
from __future__ import annotations

import pytest

from app.core.pipeline import _promote_box_title

_ITEMS = "ㄱ. A는 간기에 복제된다.\nㄴ. B는 뉴클레오타이드로 구성된다."


class TestPromote:
    def test_끝줄_보기를_올린다(self) -> None:
        src = f"<!상자><!/상자>\n{_ITEMS}\n보기\n<!상자끝><!/상자끝>"
        got = _promote_box_title(src)
        assert got.startswith("<!상자>보기<!/상자>")
        assert "\n보기\n" not in got          # 본문에서는 빠져야 한다

    def test_첫줄_보기도_올린다(self) -> None:
        src = f"<!상자><!/상자>\n보기\n{_ITEMS}\n<!상자끝><!/상자끝>"
        assert _promote_box_title(src).startswith("<!상자>보기<!/상자>")

    def test_이미_제목이_있으면_그대로(self) -> None:
        src = f"<!상자>보기<!/상자>\n{_ITEMS}\n<!상자끝><!/상자끝>"
        assert _promote_box_title(src) == src

    @pytest.mark.parametrize("first", ["▵▵고교복", "ㄱ. A는 간기에 복제된다.", "2024년"])
    def test_모르는_낱말은_안_올린다(self, first: str) -> None:
        """정답에서 관측된 제목만 올린다 — 004 p0118의 깨진 첫 줄이 실제 반례였다."""
        src = f"<!상자><!/상자>\n{first}\n뒷줄\n<!상자끝><!/상자끝>"
        assert _promote_box_title(src) == src

    def test_괄호는_원문대로_둔다(self) -> None:
        """`〈보기〉`냐 `보기`냐는 책마다 갈린다(gold 549 : 285) — 우리가 고르지 않는다."""
        src = f"<!상자><!/상자>\n{_ITEMS}\n〈보기〉\n<!상자끝><!/상자끝>"
        assert _promote_box_title(src).startswith("<!상자>〈보기〉<!/상자>")

    def test_2단계_테두리도_같이_본다(self) -> None:
        src = f"<!상자2><!/상자2>\n{_ITEMS}\n보기\n<!상자끝2><!/상자끝2>"
        assert _promote_box_title(src).startswith("<!상자2>보기<!/상자2>")

    def test_태그가_없으면_무변경(self) -> None:
        assert _promote_box_title(_ITEMS) == _ITEMS
