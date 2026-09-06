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
    assert lines[0].startswith("<!주>그래프: 시간에 따른 개체 수"), text
    assert all(l.startswith("<!2칸>") for l in lines[1:]), text   # §6.3.4(2)① 3칸
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
    assert _desc(ImageOpt, "사진: 파르테논 신전") == "<!주>사진: 파르테논 신전<!/주>"
    assert _desc(ImageOpt, "그림: 세포 모형") == "<!주>그림: 세포 모형<!/주>"


def test_번호_표지를_떼지_않는다():
    # 문항이 `①은 무엇인가` 를 묻는다 — 번호를 떼면 그 물음에 답할 수 없다.
    # 지침 예3-27 도 `① 계단 옆에 작은 분수가 있다.` 로 번호째 적는다.
    text = _desc(ImageOpt, "그림: 번호가 매겨진 사물\n① 분수\n② 화분에 꽂힌 꽃\n③ 의자")
    for mark in ("① 분수", "② 화분에 꽂힌 꽃", "③ 의자"):
        assert mark in text, text
    # 표지가 위계를 지므로 들여쓰기는 다 같은 3칸이다(gold 3칸 1,688줄 · 5칸 88줄).
    assert text.count("<!2칸>") == 3 and "<!6칸>" not in text, text


def test_묶음_머리줄을_지우지_않는다():
    # 머리줄에 들어 있다는 이유로 계열 머리를 지우면 값이 어느 계열 것인지 알 수 없다.
    cap = ("그래프: 중국 국민당군과 중국 공산당군의 병력 변화\n"
           "중국 국민당군\n1947년: 373만 명\n중국 공산당군\n1947년: 195만 명")
    text = _desc(ChartGraphOpt, cap)
    assert "중국 국민당군" in text and "중국 공산당군" in text, text


def test_너무_긴_캡션은_손대지_않는다():
    # `caption_outline` 은 40줄에서 잘린다 — 그보다 길면 뒤쪽 값이 사라지므로 종전대로 둔다.
    cap = "그래프: 아주 긴 자료\n" + "\n".join(f"항목{i}: {i}" for i in range(50))
    text = _desc(ChartGraphOpt, cap)
    assert "항목49: 49" in text, text[-80:]
