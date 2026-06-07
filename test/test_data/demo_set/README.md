# BE 데모 테스트 데이터셋 (T5-1 골격)

BE → gRPC `ProcessPage` → AI 서버 데모(T5-2)용 데이터셋. 현주 파트(레이아웃·OCR)가 미구현이므로
입력은 **TEXT_NATIVE 파일 핸드오프**(`txt_result`) 형식으로 둔다(파이프라인이 ZERO로 라우팅).

## 구성

```
demo_set/
├── manifest.json   # 페이지 목록·유형 커버리지·기대점역 작성 현황
├── pages/          # 페이지별 입력 + 기대점역 placeholder (11종)
└── README.md
```

- **11페이지**, 과목 혼합(과학·수학·사회·국어·역사·도덕·영어).
- **유형 커버리지**: text·title·list_item·formula·table·image·chart_graph·cartoon·sidebar·footnote·header_footer·page_number — 요구 혼합(text·수식·표·이미지·차트) 전부 포함.

## 페이지 파일 스키마

```json
{
  "demo_id": "p01",
  "title": "물의 상태 변화",
  "subject": "과학",
  "declared_types": ["chart_graph", "formula", "image", "list_item", "table", "text", "title", ...],
  "txt_result": {
    "meta": {"job_id": "demo-p01", "page_no": 1, "extraction_method": "TEXT_NATIVE"},
    "elements": [{"id": "...", "order": 1, "type": "title", "content": "...", "heading_level": 1}, ...]
  },
  "expected_braille": null,
  "notes": "기대 점역(점역사 작성) 미입력 — placeholder"
}
```

## ⚠ 골격 상태 — 채워야 할 것

- **`expected_braille` = null (전 페이지 placeholder)**. T5-1 완료 기준은 "각 페이지의 기대 점역 결과(점역사 작성)
  병기"다. **점역사가 페이지별 기대 점역(BRF 줄 목록)을 작성해 `expected_braille`에 채워야** 검토 기준이 된다.
  채운 뒤 `manifest.json`의 `expected_filled`를 갱신한다.
- 입력 텍스트는 데모용 예시이며, 실제 교과서 페이지로 교체·확장할 수 있다(`source` 메타 권장).

## 실행 (T5-2 데모 러너 — 스켈레톤)

```bash
python test/demo_runner.py            # 전 페이지를 파이프라인에 통과시켜 점역 출력 + FALLBACK 집계
python test/demo_runner.py --id p01   # 특정 페이지만
```

`expected_braille`가 채워진 페이지는 러너가 출력과 대조해 일치 여부를 보고한다(미입력 페이지는 출력만).

## 재생성

데이터는 생성기로 만들었다(내용은 생성기에 정의). 구조 변경 시 생성기를 고쳐 다시 출력한다.
(생성기는 일회용 스크래치라 리포지토리에 포함하지 않는다 — 생성된 JSON이 정본.)
