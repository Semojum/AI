"""응답에 싣는 끊을 자리(`FlatElement.breaks`, 이슈 #1240)와 문장 부호 앞 끊을 자리 막이.

① 문장 부호는 앞 글자가 무엇이든 그 앞에서 안 끊는다 — 「한국 점자 규정」 제49항(재추출 2114~2115행, 문장 부호
  띄어쓰기는 「한글 맞춤법」 문장 부호 규정을 따른다: 앞말에 붙여 씀) · 제51항(2346행, 쌍점의 앞은 붙여 쓴다).
  여는 괄호 앞은 끊을 수 있다(제54항 2406행은 여는 괄호 **뒤**를 붙인다).
② `_flat_breaks` 좌표 셈 — 줄 사이 구분자를 실제 길이로 센다(`_flat_trail` 과 같다).
③ 응답 통 문자열을 끊을 자리로 접은 결과가 AI 조판(`layout`)과 같다. 접는 함수는 사이드카 계약
  `Semojum/braille` `docs/sidecar.md` §5 `fold` 를 그대로 옮겼다(braille-assist `wrap` 음절 갈래가 옮길 몫).
"""
from __future__ import annotations

from uuid import uuid4

from app.ai.braille.layout_braille import LayoutBraille, _flat_breaks, flatten_elements
from app.ai.braille.translator import _break_offsets, translate_body, translate_tagged_text
from app.schemas.content import BrailleOutput
from app.schemas.layout import BBoxItem, LayoutResult

W, BLANK = 32, "⠀"


def fold(cells, breaks, center=False):
    """`docs/sidecar.md` §5 의 접기 그대로(cuts 인자만 뺐다)."""
    out, base = [], 0
    for line in cells.split("\n"):
        offs = [b - base for b in breaks if base < b < base + len(line)]
        base += len(line) + 1
        if not offs:
            offs = [i for i, c in enumerate(line) if c == BLANK and i and line[i - 1] != BLANK]
        seg, start = [], 0
        while len(line) - start > W:
            ok = [b for b in offs if start < b <= start + W]
            b = max(ok) if ok else start + W
            if not ok and line[b - 1] == "⠠" and line[b] == "⠄":
                b -= 1
            seg.append(line[start:b])
            start = b
            while start < len(line) and line[start] in (" ", BLANK):
                start += 1
        if start < len(line) or not seg:
            seg.append(line[start:])
        if center and len(line) > W:
            seg = [BLANK * ((W - len(s)) // 2) + s for s in seg]
        out += seg
    return out


def _cut_before(src: str, head: str) -> bool:
    """`src` 를 점역한 줄에서 `head` 뒤(그 다음 글자 앞)가 끊을 자리인가."""
    br = translate_tagged_text(src)
    return len(translate_tagged_text(head)) in _break_offsets(src, br)


# ── ① 문장 부호 앞 ─────────────────────────────────────────────────────────

def test_전각_쌍점_앞은_안_끊는다():
    assert not _cut_before("공평한 기회：전문적 자격", "공평한 기회")


def test_한글_아닌_글자_뒤_쉼표_앞도_안_끊는다():
    assert not _cut_before("세포, □□, □□, 기관", "세포, □□")
    # 로마자 구간은 앞부분만 점역하면 종료표 ⠲ 가 붙어 길이가 어긋난다 — 쉼표 셀(⠂, 통일영어점자) 자리를 직접 본다.
    src = "측정 DO, BOD, COD"
    br = translate_tagged_text(src)
    assert br.index("⠙⠂") + 1 not in _break_offsets(src, br)


def test_닫는_태그_뒤_마침표_앞도_안_끊는다():
    assert not _cut_before("귀결되고 있다<!/드러냄>. 그러므로", "귀결되고 있다")


def test_여는_괄호_앞은_끊는다():
    assert _cut_before("스며들다[스며 나오다]", "스며들다")


def test_스위치를_끄면_종전(monkeypatch):
    monkeypatch.setenv("BREAK_PUNCT_ANY", "0")
    assert _cut_before("세포, □□, □□, 기관", "세포, □□")       # 종전: 한글 뒤만 막았다


# ── ② 좌표 셈 ────────────────────────────────────────────────────────────

def test_좌표는_들임과_실제_구분자_길이로_센다():
    # "⠀⠀⠁⠀⠃" + 이음 빈칸 + "⠉⠀⠙": 첫 줄 빈칸 앞 3 · 이음 빈칸 앞 5 · 둘째 줄 빈칸 앞 7
    assert _flat_breaks(["⠁⠀⠃", "⠉⠀⠙"], [2, 0], [[], []], 0, ["⠀"]) == (3, 5, 7)
    # 앞 줄이 빈칸으로 끝나면 구분자가 빈 글자다 — 뒤 줄 좌표가 한 칸 밀리면 안 된다.
    assert _flat_breaks(["⠁⠀⠃⠀", "⠉⠀⠙"], [0, 0], [[], []], 0, [""]) == (1, 3, 5)
    # 개행 뒤 줄 · 앞 빈 줄(prefix) 만큼 민다. 줄머리 빈칸 안에서는 안 끊는다.
    assert _flat_breaks(["⠀⠀⠁⠀⠃"], [0], [[1, 3]], 2) == (5,)


# ── ③ 접은 결과 = AI 조판 ───────────────────────────────────────────────

_PARA = ("조선 후기에는 상품 화폐 경제가 발달하면서 장시가 크게 늘어났고, 보부상의 활동이 활발해졌다. "
         "또한 대동법의 시행으로 공인이 등장하여 관청에 물품을 조달하였으며, 이들은 점차 독점적 도매상인으로 성장하였다.")


def _flat_and_layout(text: str, etype: str = "text", hlevel: int = 0):
    out = []
    for flat in (True, False):
        lines, breaks = translate_body(text)
        bo = BrailleOutput(element_id=uuid4(), corrected_text=text, braille_lines=lines, break_points=breaks)
        lr = LayoutResult(page_id="p1", elements=[BBoxItem(element_id=bo.element_id, type=etype, bbox=(0, 0, 1, 1),
                                                           reading_order=1, heading_level=hlevel or None)])
        if flat:
            fe = flatten_elements([bo], lr)[bo.element_id]
            out.append(fe)
        else:
            LayoutBraille().layout([bo], page_no=1, job_id="t", layout_result=lr)
            out.append(bo.braille_lines)
    return out


def test_끊을_자리로_접으면_AI_조판과_같다():
    fe, lay = _flat_and_layout(_PARA)
    assert fe.breaks and all(0 < b < len(fe.text) and fe.text[b] != "\n" for b in fe.breaks)
    got = [ln for ln in fold(fe.text, fe.breaks) if ln]
    assert len(got) >= 3 and got == [ln for ln in lay if ln]


def test_음절로_접어야_어절보다_줄이_덜_빈다():
    """같은 문단을 빈칸에서만 접으면(어절, 끊을 자리 모름) 줄 끝이 더 빈다 — 끊을 자리가 실제로 쓰였다는 표지."""
    fe, _ = _flat_and_layout(_PARA)
    syl, word = fold(fe.text, fe.breaks), fold(fe.text, [])
    assert len(syl) <= len(word) and any(len(a) != len(b) for a, b in zip(syl, word))


def test_묶은_선택지_줄도_자리가_맞다():
    """#1238 이 묶은 3-2 줄(지침 [예 3-68] 3470~3471행)도 끊을 자리가 유효하고, 32칸 안이라 접어도 그대로다."""
    rows = ["⠀⠀⠼⠂⠀⠶⠴⠁⠶⠀⠀⠼⠆⠀⠶⠴⠃⠶⠀⠀⠼⠒⠀⠶⠴⠉⠶", "⠀⠀⠼⠲⠀⠶⠴⠙⠶⠀⠀⠼⠢⠀⠶⠴⠑⠶"]
    fe, _ = _flat_and_layout("①ⓐ\n②ⓑ\n③ⓒ\n④ⓓ\n⑤ⓔ", etype="list_item")
    assert fe.text.strip("\n").split("\n") == rows
    assert fe.breaks and all(0 < b < len(fe.text) and fe.text[b] != "\n" for b in fe.breaks)
    assert [ln for ln in fold(fe.text, fe.breaks) if ln] == rows
