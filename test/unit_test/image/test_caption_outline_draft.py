"""캡션의 위계 줄이 그대로 개조식 골격이 되는가 (2026-09-07).

근거 — 「점자 자료 제작 지침」 §6.1.4(4) 전체 윤곽→부분 · (6) 개조식 표현,
§6.3.4(2)① "다음 줄에 원본 시각 자료에 포함된 내용을 적는다".
도서지침 예3-32~3-36 은 그래프 값을 `항목: 값` 한 줄씩 적는다.

종전에는 앞단이 `ocr_texts`·`data_points` 를 한 번도 안 주는 탓에 항목이 늘 비었고,
여러 줄 캡션이 `_oneline` 에 접혀 **점역자 주 한 줄**로 나갔다(실측 캡션 1,811건 중
이미지·차트 경로 1,019건 전부). ZERO 티어는 LLM 미사용이라 결정적이다.
"""
from __future__ import annotations

import asyncio
import re
from uuid import uuid4

from app.ai.llm.chart_graph_opt import ChartGraphOpt
from app.ai.llm.image_opt import ImageOpt
from app.schemas.content import ExtractedContent

_TAG = re.compile(r"<!/?[^>]*>")


def _desc(cls, caption: str):
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text=caption, structure={})
    out = asyncio.run(cls().optimize([ext], "ZERO"))[0]
    return out.drafts[out.selected_idx].text


def test_캡션_줄이_개조식_항목이_된다():
    text = _desc(ChartGraphOpt,
                 "그래프: 시간에 따른 개체 수\n가로축: 시간\n세로축: 개체 수(천 마리)\nㄱ: 실선")
    lines = text.split("\n")
    assert len(lines) == 4, text                       # 머리줄 + 항목 셋
    # ★ 2026-09-07 계약 변경 — 머리줄도 **3칸**이다(`<!2칸>`). 종전에는 머리줄만 들여쓰기
    #   태그가 없어 1칸으로 나갔는데, 도서지침 3장 2절 4)(1)(2)(L2368·L2384) 가 "3칸에서
    #   시작하여 점역자 주표 안에 …" 라 못 박고 gold 원본 BRF 전수(시각 머리줄 4,183건)도
    #   3칸 81.0% · 5칸 18.9% · **1칸 3건(0.07%)** 이다.
    # ★ 2026-09-10 원장 C-D4 재판정 — 점역자 주표가 **설명·전사 항목까지** 감싸고
    #   덩이 끝에서 닫는다. 우리 초안은 캡셔너가 지어 쓴 설명이라 도서지침 3장 2절
    #   4)**(3)**①(L2400-2401) 갈래다. 4)(1)(2)(L2368) 는 원본에 인쇄된 글을 옮길 때다.
    assert lines[0].startswith("<!2칸><!주>그래프: 시간에 따른 개체 수"), text
    assert lines[-1].endswith("<!/주>"), text          # 덩이 끝에서 닫는다
    assert "<!/주>" not in lines[0], text              # 머리줄에서 닫지 않는다
    assert all(l.startswith("<!2칸>") for l in lines[1:]), text   # 항목도 같은 3칸
    assert "세로축: 개체 수(천 마리)" in text          # 값을 흘리지 않는다


def test_유형_제시어를_두_번_찍지_않는다():
    # 캡셔너가 `_ensure_type_word` 로 붙인 제시어 위에 모델이 자기 종류어를 또 쓴다
    # (실측 1,814건 중 651건). 쌍점형·쉼표형 둘 다 한 겹으로 접는다.
    for cap in ("그래프: 꺾은선그래프: 생존 곡선\n가로축: 나이",
                "그래프: 막대그래프, 생존 곡선\n가로축: 나이"):
        head = _TAG.sub("", _desc(ChartGraphOpt, cap)).split("\n")[0]
        assert head == "그래프: 생존 곡선", head


def test_사진_캡션은_사진으로_나간다():
    # §6.3.4(1) 유형 제시어. 캡셔너 image 프롬프트가 사진이면 `사진: `으로 시작시킨다.
    # 머리줄 3칸(`<!2칸>`)은 2026-09-07 계약 — 위 test 주석 참조.
    # 주표 범위는 위 test 주석 참조(원장 C-D4 재판정 2026-09-10) — 설명까지 주 안이다.
    assert _desc(ImageOpt, "사진: 파르테논 신전") == "<!2칸><!주>사진: 파르테논 신전<!/주>"
    assert _desc(ImageOpt, "그림: 세포 모형") == "<!2칸><!주>그림: 세포 모형<!/주>"


def test_번호_표지를_떼지_않는다():
    # 문항이 `①은 무엇인가` 를 묻는다 — 번호를 떼면 그 물음에 답할 수 없다.
    # 지침 예3-27 도 `① 계단 옆에 작은 분수가 있다.` 로 번호째 적는다.
    text = _desc(ImageOpt, "그림: 번호가 매겨진 사물\n① 분수\n② 화분에 꽂힌 꽃\n③ 의자")
    for mark in ("① 분수", "② 화분에 꽂힌 꽃", "③ 의자"):
        assert mark in text, text
    # 표지가 위계를 지므로 들여쓰기는 다 같은 3칸이다(gold 3칸 1,688줄 · 5칸 88줄).
    # 넷인 것은 머리줄까지 3칸이 됐기 때문이다(2026-09-07 계약).
    assert text.count("<!2칸>") == 4 and "<!6칸>" not in text, text


def test_묶음_머리줄을_지우지_않는다():
    # 머리줄에 들어 있다는 이유로 계열 머리를 지우면 값이 어느 계열 것인지 알 수 없다.
    cap = ("그래프: 중국 국민당군과 중국 공산당군의 병력 변화\n"
           "중국 국민당군\n1947년: 373만 명\n중국 공산당군\n1947년: 195만 명")
    text = _desc(ChartGraphOpt, cap)
    assert "중국 국민당군" in text and "중국 공산당군" in text, text


def test_긴_캡션도_값을_한_줄씩_싣는다():
    """본문 41줄이 넘어도 뒤쪽 값 줄이 사라지지 않는다 (재구조화 4-1, 2026-09-08).

    종전에는 `caption_outline` 의 `_MAX_LINES`(40) 때문에 이 갈래를 건너뛰고 LLM 으로
    넘겼고, 프롬프트가 `[개조식] … 3~5줄` 을 시켜 **값이 요약돼 사라졌다**
    (제품 실측: 본문 46줄·값 39개 → 초안 6줄·값 0개).
    """
    cap = "그래프: 아주 긴 자료\n" + "\n".join(f"항목{i}: {i}" for i in range(50))
    text = _desc(ChartGraphOpt, cap)
    lines = text.split("\n")
    assert len(lines) == 51, len(lines)                  # 머리줄 + 항목 50
    for i in (0, 39, 40, 49):                            # 40줄 문턱 앞뒤를 콕 집어 본다
        assert f"항목{i}: {i}" in text, (i, text[-120:])
    assert all(l.startswith("<!2칸>") for l in lines), text[:120]


# ★ 2026-09-08(재구조화 5단계) — 아래 다섯 검사는 원래 `vd.generate_with_retry` 를
#   계수 스텁으로 갈아 끼우고 "호출 0회" 를 단언했다. **그 팔을 지웠으므로** 스텁을
#   걸 자리가 없다. 팔이 정말 없는지는 `test_opt_prompts.test_시각_4안에는_프롬프트가_없다`
#   가 잡고, 여기서는 그 자리를 대신 채운 **규칙 전사의 결과**만 남긴다 — 값이 다 실리는가,
#   제목만 있으면 생략으로 가는가, 한 줄 캡션에 없는 말이 안 붙는가.
def test_긴_캡션은_값을_다_싣는다() -> None:
    """값이 다 실리므로 요약을 시킬 이유가 없다 — #698 이 41줄 상한을 걷은 이유다."""
    cap = "그래프: 아주 긴 자료\n" + "\n".join(f"항목{i}: {i}" for i in range(50))
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text=cap, structure={})
    out = asyncio.run(ChartGraphOpt().optimize([ext], "STANDARD"))[0]
    assert "항목49: 49" in out.drafts[out.selected_idx].text


def test_제목만_있으면_생략으로_간다() -> None:
    """재구조화 2단계 — 관문이 캡션을 걷어내면 열리던 환각 폴백의 입구를 막았다.

    실측(2026-09-07, 판단장부 §2): 캡션이 비고 제목만 남은 요소에서 L8 이
    `사진: 쿠트브 미나르` → 넉 줄("인도 델리에 있는 …")을 지어냈고 넉 줄 다 자료에 없는 말이다.
    규정 §6.3.4(2)② 의 정답은 그 자리에서 생략 표기이고, R11 은 품질검사가 세운다.
    """
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text="", structure={"title": "표제만 있는 그림"})
    out = asyncio.run(ImageOpt().optimize([ext], "STANDARD"))[0]
    assert len(out.drafts) == 1 and "생략" in out.drafts[0].text, out.drafts


def test_캡션에_없는_말이_안_붙는다() -> None:
    """캡션이 한 줄이면 그 줄이 완성된 설명이다 — 늘리면 지어낸다.

    실측(2026-09-07 · claude-sonnet-5 폴백, 캡션 캐시 사진 56 · 그림 100):
    캡션 밖 문장을 한 줄도 안 붙인 초안이 사진 1/56 · 그림 16/100 뿐이었고
    지어낸 줄이 409줄이었다. gold 는 사진 설명 54건 중 38건이 항목 한 개다.
    """
    from app.ai.llm import visual_drafts as vd

    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text="사진: 쿠트브 미나르", structure={})
    out = asyncio.run(ImageOpt().optimize([ext], "STANDARD"))[0]
    assert _TAG.sub("", out.drafts[out.selected_idx].text) == "사진: 쿠트브 미나르"

    # 여러 줄 캡션도 캡션 줄이 그대로 골격이 되고, 짧은 안은 그 골격에서 **항목만 지운**
    # 간추린 설명이다 — 지어낼 자리가 없다.
    ext2 = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                            corrected_text="사진: 술탄 아흐메드 사원\n큰 돔 지붕 주위에 첨탑 여섯 개",
                            structure={})
    out2 = asyncio.run(ImageOpt().optimize([ext2], "STANDARD"))[0]
    gist = [d for d in out2.drafts if d.option == vd.GIST_OPTION]
    assert gist, [d.label for d in out2.drafts]
    body = _TAG.sub("", gist[0].text)
    assert body == "사진: 술탄 아흐메드 사원", body      # 머리줄 그대로 — 새 말이 없다
    assert body in _TAG.sub("", out2.drafts[out2.selected_idx].text)
