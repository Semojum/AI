import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

PAGE_NO    = 1
_TEST_DATA = Path(__file__).parents[2] / "test_data" / "page_001"
LAYOUT_JSON = _TEST_DATA / "merged_layout.json"
MINERU_RAW  = _TEST_DATA / "mineru_raw"

_PROJECT_ROOT = Path(__file__).parents[3]

VALID_TYPES = {
    "title", "text", "caption", "formula", "list_item",
    "footnote", "sidebar", "header_footer", "page_number",
    "table", "image", "chart", "cartoon",
}


def test_fixture_exists():
    assert LAYOUT_JSON.exists(), f"fixture 없음: {LAYOUT_JSON}"
    assert MINERU_RAW.is_dir(), f"fixture 없음: {MINERU_RAW}"


def _load():
    return json.loads(LAYOUT_JSON.read_text(encoding="utf-8"))


def test_merged_layout_schema():
    """필수 필드 전체 존재, type이 13종 이내."""
    data = _load()
    assert len(data) > 0
    for el in data:
        for key in ("element_id", "reading_order", "type", "bbox", "image_path", "flags"):
            assert key in el, f"'{key}' 필드 없음: {el}"
        assert el["type"] in VALID_TYPES, f"알 수 없는 type: {el['type']}"


def test_image_path_format():
    """image_path가 있으면 mineru_raw/images/{uuid}.jpg 형식이고 파일 존재."""
    data = _load()
    for el in data:
        if el["image_path"] is None:
            continue
        p = _PROJECT_ROOT / el["image_path"]
        assert p.exists(), f"image_path 파일 없음: {p}"
        assert "mineru_raw/images" in el["image_path"].replace("\\", "/"), \
            f"경로 형식 불일치: {el['image_path']}"
        stem = p.stem
        assert len(stem) == 36, f"파일명이 UUID 형식이 아님: {stem}"


def test_no_unnecessary_files():
    """불필요 파일(*_v2.json, *.md, *_layout.pdf, *_origin.pdf) 없음."""
    for pattern in ("*_content_list_v2.json", "*.md", "*_layout.pdf", "*_origin.pdf"):
        found = list(MINERU_RAW.rglob(pattern))
        assert len(found) == 0, f"불필요 파일 존재 ({pattern}): {found}"


def test_mineru_raw_images_dir():
    """mineru_raw/images/ 폴더 존재."""
    assert (MINERU_RAW / "images").is_dir(), "mineru_raw/images/ 폴더 없음"


def test_mineru_raw_flat_structure():
    """mineru_raw/ 바로 아래에 *.json 파일이 있어야 함 (중첩 서브디렉토리 아님)."""
    json_files = list(MINERU_RAW.glob("*.json"))
    assert len(json_files) > 0, "mineru_raw/ 루트에 JSON 파일 없음"


def test_no_review_needed_flag():
    """REVIEW_NEEDED 플래그가 없음."""
    data = _load()
    for el in data:
        assert "REVIEW_NEEDED" not in el["flags"], \
            f"REVIEW_NEEDED 플래그 발견: element_id={el['element_id']}"


# ── 제목 단계(BBPG 2장2절1) — QA S1, 2026-08-07 ──────────────────────────────
# MinerU는 제목 블록을 이미 찾아 두는데 content_list에서 type이 "text"로 눕고 단계만
# text_level에 남는다. 종전에는 그 값을 버려 조판이 제목 규칙을 한 번도 못 썼다
# (QA 실측: 37쪽 558요소에 title 0개). 다만 그 표시의 35%는 문항 발문·선택지라
# 그대로 믿으면 발문이 가운데 정렬로 나간다.
from app.ai.parser.mineru_runner import _heading_level


class TestHeadingLevel:
    def test_lv1은_2단계(self):
        """MinerU lv1 = 강 제목 = BBPG 2단계(7칸). 1단계(가운데)가 아니다.

        dev·val-2027 gold 전수: 앞빈칸 6칸 455줄 vs 가운데(앞 7칸 이상) 89줄.
        6칸 455줄 중 292줄이 가운데 계산 `(32-길이)//2` 와 어긋나 **고정 들여쓰기**임이
        증명된다. 우리가 가운데꼴로 내던 26줄 중 21줄을 gold 는 6칸으로 적는다.
        (2026-08-28, 원장 C-79)
        """
        assert _heading_level({"text_level": 1}, "text", "서유럽 봉건 사회의 전개와 문화") == 2

    def test_번호_붙은_제목도_제목(self):
        assert _heading_level({"text_level": 1}, "text", "1. 제국주의와 제1차 세계 대전") == 2

    def test_lv2이상은_4단계(self):
        # 정답 도서 실측(refonly 94권): 2단계 7칸은 0.18%로 거의 안 쓰고 3·4단계 5칸이 1.45%.
        # 그 5칸 시작 줄 1,651줄은 위에 빈 줄 26.7% · 아래 2.7%라 4단계(1,0) 모양이다
        # (2026-08-08 대표 결정). 3단계(1,1)로 두면 아래 빈 줄이 계속 들어간다.
        assert _heading_level({"text_level": 2}, "text", "송대의 전시(殿試)") == 4
        assert _heading_level({"text_level": 3}, "text", "보기") == 4

    def test_선택지는_제목_아님(self):
        assert _heading_level({"text_level": 2}, "text", "① 삼국 동맹의 성립") is None

    def test_발문은_제목_아님(self):
        assert _heading_level({"text_level": 1}, "text", "01 (가) 나라에 대한 설명으로 옳은 것은?") is None
        assert _heading_level({"text_level": 2}, "text",
                              "위 글을 참고하여 <보기>를 이해한 반응으로 적절하지 않은 것은?") is None

    def test_긴_문장은_제목_아님(self):
        assert _heading_level({"text_level": 1}, "text", "가" * 29) is None
        assert _heading_level({"text_level": 1}, "text", "가" * 28) == 2

    def test_표시_없으면_None(self):
        assert _heading_level({}, "text", "제목처럼 보여도") is None

    def test_글이_아닌_유형은_제외(self):
        assert _heading_level({"text_level": 1}, "image", "그림") is None
        assert _heading_level({"text_level": 1}, "table", "표") is None


class TestMineruRetry:
    """MinerU 는 같은 지면·같은 코드에서도 비결정으로 죽는다. 한 번 더 부르면 살아난다.

    실측(시연 12쪽, 2026-08-26): 07:26 판 폴백 0 · 12:27 판 2 · 13:15 판 1 ·
    13:14 같은 쪽 재시도 성공. 폴백은 인쇄 줄 하나가 요소 하나라 표·그림 구조가 사라진다.
    """

    def test_한_번_실패하면_다시_부른다(self, tmp_path, monkeypatch):
        from app.ai.parser import mineru_runner as M
        calls = []

        def flaky(pdf_path, out_dir, page_idx, timeout=None):
            calls.append(page_idx)
            if len(calls) == 1:
                raise RuntimeError("MinerU 실행 실패 (returncode=1, page_idx=0)")
            (out_dir / "x_content_list.json").write_text("[]", encoding="utf-8")

        monkeypatch.setattr(M, "_run_mineru", flaky)
        monkeypatch.setattr(M, "_cleanup_mineru_output", lambda d: None)
        monkeypatch.setattr(M, "_flatten_mineru_output", lambda d: None)
        raw = tmp_path / "mineru_raw"
        raw.mkdir()
        # 호출부와 같은 얼개를 그대로 태운다
        for attempt in range(1 + M._MINERU_RETRIES):
            try:
                M._run_mineru(tmp_path / "a.pdf", raw, 0, timeout=None)
                break
            except M.MineruTimeout:
                raise
            except RuntimeError:
                if attempt >= M._MINERU_RETRIES:
                    raise
        assert len(calls) == 2, calls

    def test_타임아웃은_재시도하지_않는다(self):
        """예산을 이미 다 썼다 — 다시 부르면 두 배다. 종전대로 폴백으로 간다."""
        from app.ai.parser.mineru_runner import MineruTimeout
        assert issubclass(MineruTimeout, RuntimeError)

    def test_폴백은_살아_있다(self):
        """재시도가 다 실패하면 예외가 올라가고 호출자가 텍스트 폴백으로 간다."""
        from app.ai.parser import mineru_runner as M
        assert M._MINERU_RETRIES >= 1
