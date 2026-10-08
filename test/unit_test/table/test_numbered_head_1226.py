"""번호 체계 표의 첫 행 칸이 문장이면 열 제목이 아니라 자료 행이다(#1226).

머리행 없이 첫 행부터 자료인 표에서 첫 행을 열 제목으로 쓰면, 첫 행 내용이 다른 행마다 `가.` 열 이름으로
되풀이되고 첫 행은 자료로 안 나간다. gold 는 첫 행을 자료로 적는다(세계사 body p0018 `1. 특징` +
`• 북조: …`, 언매 body p0019 `조사` + `격 조사: …`). 표 글은 d8c 경계 HTML 을 `_html_to_grid(expand=False)` 로 편 것.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille import table_braille as B  # noqa: E402

# 세계사 body p0018(d8c page_028) — 첫 행 `특징` 이 두 칸을 덮는 자료 행
_WORLD = ("특징 | • 북조 : 유목민의 문화와 한족 문화가 융합, 국가적 차원에서 유교 존중• 남조 : 귀족 중심의 문화 발달\n"
          "종교 | 불교 | 북조 황실의 후원으로 발전, 대규모 석굴 사원 조성\n"
          "도교 | 태평도, 오두미도가 도가 사상과 결합하여 도교로 발전")
# 열 제목이 있는 문장 표(칸이 모두 짧다)
_HEAD = ("구분 | 공자 | 맹자\n"
         "인간관 | 인(仁)을 갖춘 사람이 되려고 노력해야 한다고 봄 | 사람은 누구나 선한 본성을 타고난다고 봄")


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.delenv("TABLE_NUMBERED_HEAD", raising=False)


def test_첫_행이_자료면_첫_행부터_번호를_매긴다():
    out = B.print_layout(_WORLD, "numbered").splitlines()
    assert out[0] == "1. 특징" and "2. 종교" in out and "3. 도교" in out
    assert sum("북조 : 유목민" in l for l in out) == 1          # 첫 행 내용이 되풀이되지 않는다


def test_칸이_모두_짧으면_첫_행은_열_제목이다():
    out = B.print_layout(_HEAD, "numbered").splitlines()
    assert out[:3] == ["1. 인간관", "  가. 공자", "    인(仁)을 갖춘 사람이 되려고 노력해야 한다고 봄"]


def test_점자_쪽도_같은_판정을_쓴다():
    """묵자 미리보기와 점자가 어긋나면 점역사가 다른 안을 보고 고른다(print_layout 주석)."""
    assert B._translate("1. 특징") in "\n".join(B._render_numbered(_WORLD))


def test_끄면_종전대로_첫_행을_열_제목으로(monkeypatch):
    monkeypatch.setenv("TABLE_NUMBERED_HEAD", "0")
    assert B.print_layout(_WORLD, "numbered").splitlines()[0] == "1. 종교"


@pytest.mark.parametrize("head", [
    "구분 | 타원형 계층 구조 | 모래시계형 계층 구조",            # 사회문화 d8c page_170 — 11자, 종전 10자 문턱이 자료로 잘못 봄
    "매체 자료 | 정보 표현에 사용되는 언어 | 창의적 표현 방법",     # 언매 d8c page_075 — 14자
    "구분 | ‘안’ 부정문(단순 부정, 의지 부정) | ‘못’ 부정문(능력 부정)",  # 괄호 속 쉼표는 문장 표지가 아니다
    "구분 | 사회·문화 현상 | 자연 현상",                       # 가운뎃점은 글머리가 아니다
])
def test_긴_열_제목도_열_제목이다(head):
    assert B._numbered_split([[c.strip() for c in head.split("|")], ["값", "값"]])[0] != []


@pytest.mark.parametrize("first", [
    "국내 | 환관 득세, 향촌 질서 동요",                        # 동아시아사 d8c page_105 — 괄호 밖 쉼표
    "연구 주제 | 학교 밖 청소년들의 사이버불링 피해 경험",       # 사회문화 d8c page_040 — 20자 넘는 문장(표지 없음)
    "자선의관점 | 노직 | · 자유 지상주의: 정당한 절차를 통해 취득한 재산에 대해",  # 생활과 윤리 d8c page_210 — 칸 첫머리 글머리
])
def test_문장인_첫_행은_자료다(first):
    assert B._numbered_split([[c.strip() for c in first.split("|")], ["값", "값"]])[0] == []
