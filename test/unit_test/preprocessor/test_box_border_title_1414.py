"""#1414 글자층 테두리 제목 — 제목 요소가 없을 때 윗변에 걸친 `보기` 를 상자 제목으로 쓴다.

「점자 도서 제작 지침」 1장 2절 5. 2)(4)②(재추출 400~402행): 위 테두리에 위치한 제목은 위 테두리 7칸에 적되 양옆을 한 칸씩 띈다.
"""
from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import _border_title, tag_boxed_elements

RECT = [169.0, 249.5, 345.0, 301.0]          # 윗변 y=249.5 가 `◀ 보기 ▶` 글(245~254) 가운데를 지난다


def test_윗변에_걸친_보기는_제목이다():
    assert _border_title([("◀ 보기 ▶", [175, 245, 199, 254])], RECT) == "보기"
    assert _border_title([("◀", [175, 245, 179, 254]), (" 보기 2 ", [181, 245, 197, 254]), ("▶", [198, 245, 202, 254])], RECT) == "보기 2"


def test_보기_밖의_글이나_윗변에_안_걸친_글은_제목이_아니다():
    assert _border_title([("예제1", [175, 245, 199, 254])], RECT) == ""          # gold 는 테두리 제목으로 안 적는다
    assert _border_title([("01", [175, 245, 199, 254])], RECT) == ""
    assert _border_title([("보기", [175, 262, 199, 271])], RECT) == ""           # 상자 안 첫 줄(윗변에 안 걸침)
    assert _border_title([("보기", [400, 245, 420, 254])], RECT) == ""           # 상자 가로 밖


def test_제목_요소가_없으면_글자층_제목을_쓴다():
    els = [{"type": "text", "bbox": [180, 262, 330, 296], "content": "ㄱ. 가\nㄴ. 나"}]
    assert tag_boxed_elements(els, [RECT], titles={tuple(RECT): "보기"}) == 1
    assert els[0]["content"].startswith("<!상자>보기<!/상자>\n")


def test_제목_요소가_있으면_그것을_쓴다():
    els = [{"type": "text", "bbox": [175, 244, 205, 255], "content": "자료"},
           {"type": "text", "bbox": [180, 262, 330, 296], "content": "ㄱ. 가"}]
    tag_boxed_elements(els, [RECT], titles={tuple(RECT): "보기"})
    body = "\n".join(e["content"] for e in els)          # 올라간 제목 요소는 목록에서 빠진다
    assert "<!상자>자료<!/상자>" in body and "보기" not in body


def test_점자는_위_테두리_7칸에_양옆_한_칸():
    first = translate_tagged_text("<!상자>보기<!/상자>\nㄱ. 가\n<!상자끝><!/상자끝>").split("\n")[0]
    assert first.startswith("⠿⠛⠛⠛⠛⠀⠘⠥⠈⠕⠀⠛") and first.endswith("⠿") and len(first) == 32



def test_몸통에_섞여_온_제목_줄은_떼어_제목으로_올린다():
    # 탭이 글 블록에 줄로 섞여 온 자리(대개 몸통 끝 줄). 떼지 않으면 `보기` 가 제목 · 본문에 두 번 나간다.
    merged = [{"type": "text", "bbox": [180, 262, 330, 296], "content": "ㄱ. 가\nㄴ. 나\n보기"}]
    tag_boxed_elements(merged, [RECT], titles={tuple(RECT): "보기"})
    assert merged[0]["content"] == "<!상자>보기<!/상자>\nㄱ. 가\nㄴ. 나\n<!상자끝><!/상자끝>"
    lone = [{"type": "text", "bbox": [246, 245, 303, 256], "content": "보기"}]      # 제목 요소뿐이라 본문으로 되돌린 상자
    tag_boxed_elements(lone, [RECT], titles={tuple(RECT): "보기"})
    assert lone[0]["content"].count("보기") == 1
