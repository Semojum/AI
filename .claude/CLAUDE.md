# code/AI/ — Python AI 서버 구현 코드

> 전역/프로젝트 규칙은 상위 `~/.claude/CLAUDE.md` + `V2/.claude/CLAUDE.md` + `code/.claude/CLAUDE.md`에서 자동 로드. 여기서 반복 안 함.
> 이 파일은 **현재 코드의 실제 상태**(어디에 무엇이 있고 무엇이 stub인지)를 기술한다.
> **권위 순서(이 프로젝트 지침)**: 설계 의도가 충돌하면 `../../plan/`이 우선이다. 즉 코드가 plan과 다르면 **plan이 정본이고 코드를 고쳐야 한다**(아래 "plan 대비 코드 변경 필요" 섹션). 이 파일은 "코드가 지금 이렇다"를 알려주되, "이렇게 되어야 한다"는 plan을 따른다.

목적: 다음 세션 AI가 파일을 전부 열지 않고도 **어디에 무엇이 있고, 공개 진입점이 무엇이며, 무엇이 plan과 어긋나거나 미구현인지** 파악하게 한다.

---

## 한 줄 개요

점역사 보조용 한국어 점자(BRF) 초안 생성 AI 서버. `BE ──gRPC(50051)──▶ 이 서버 ──gRPC(50052)──▶ PP-FormulaNet`. FastAPI(8080)로 헬스체크. 페이지 단위 처리, 180초 하드 타임아웃.

---

## 디렉토리 맵 (실제 파일 + 역할)

```
app/
├── core/                         # 서버 진입점 · 오케스트레이션
│   ├── main.py          create_app(FastAPI) + _run_grpc/_run_rest + main() — gRPC·REST 동시 기동
│   ├── config.py        Settings(pydantic-settings) 싱글톤 `config`. .env 로드. is_debug, max_grpc_message_bytes
│   ├── grpc_server.py   PART 1·12. BrailleServiceServicer.ProcessPage, serve(), dict→proto 변환기들
│   ├── pipeline.py      ★ 오케스트레이터. run(task) 180s 타임아웃 → _run_pipeline → 6-체인 gather → _build_response(dict)
│   ├── model_manager.py ModelManager 싱글톤. load_all → GPU0/GPU1 정적 로드. 모델 property + get_status()
│   ├── health_check.py  PART 1-REST. get_health(), get_models_status() (dict 반환)
│   └── routes.py        FastAPI 라우터: GET /health, GET /models/status
├── schemas/                      # Pydantic v2 내부 데이터 모델 (proto와 별개)
│   ├── task.py          PageTask + from_proto(req) — gRPC 요청 → 내부 표현
│   ├── layout.py        BBoxItem, LayoutResult, DocumentMeta
│   ├── content.py       RuleApplication, ExtractedContent, LLMOutput, BrailleOutput
│   └── quality.py       CriticalError(C1~C7), ReviewFlag(R1~R12), QualityReport
├── ai/
│   ├── preprocessor/             # PART 2
│   │   ├── pdf_analyzer.py  analyze_pdf(pdf_data,page_idx,job_id)→(DocumentMeta, zero_text). 신뢰도·티어 산출, 헤더/푸터 감지
│   │   └── converter.py     convert_page(...)→PIL. DPI 변환 + _binarize_and_deskew (Otsu+deskew)
│   ├── layout/                   # PART 3
│   │   ├── qwen_layout.py   QwenLayout.detect(image)→list[dict]. _parse_json, _run_inference
│   │   ├── yolo_layout.py   YoloLayout.detect(image)→list[dict] (보조 hint)
│   │   └── layout_merger.py LayoutMerger.merge(...)→LayoutResult. _iou, _assign_reading_order, _link_captions
│   ├── ocr/
│   │   ├── qwen_ocr.py      PART 4-1. QwenOCR.process(layout,image,tier,zero_text)→list[ExtractedContent]
│   │   └── formula_ocr.py   PART 5-1. FormulaOCR.process(crops). FormulaNet gRPC, _latex_complexity, _validate_latex
│   ├── captioning/              # 진입점 모두 .process(...)
│   │   ├── classifier.py        PART 3-4. ImageClassifier.classify(layout, image)→LayoutResult (image→cartoon/chart_graph 확정)
│   │   ├── table_cap.py         PART 6-1. TableCap.process(crops, tier)  (Docling TableFormer)
│   │   ├── image_cap.py         PART 7-1. ImageCap.process(crops)        (GPT-4o)
│   │   ├── cartoon_cap.py       PART 8-1. CartoonCap.process(crops)      (GPT-4o)
│   │   └── chart_graph_cap.py   PART 9-1. ChartGraphCap.process(crops)   (GPT-4o)
│   ├── llm/                     # PART *-2. 진입점 .optimize(extracted, tier[, layout])→list[LLMOutput]
│   │   ├── text_opt.py · formula_opt.py · table_opt.py · image_opt.py · cartoon_opt.py · chart_graph_opt.py
│   │   │   각: Class*Opt.optimize + _hcxt_generate_sync + _hcxt_optimize(HyperCLOVA X) + _fallback_optimize(GPT API)
│   │   │   table_opt: _table_to_text, _infer_render_mode, _parse_tn_from_response
│   │   │   chart_graph_opt: _verify_numbers (숫자 환각 검증)
│   ├── braille/                 # PART *-3 + 공통 엔진. 진입점 .translate(list[LLMOutput])→list[BrailleOutput]
│   │   ├── translator.py    ★ 코어. translate_tagged_text(text)→점자. braillify(있으면)/폴백 분기, _emit_mixed 세그먼트 분리
│   │   ├── symbol_rules.py   substitute_symbols(text), preprocess/postprocess. symbol_table.json 로드(_load_flat_table)
│   │   ├── symbol_table.json 기호→점자 매핑 데이터
│   │   ├── kor_math_rules.py ★ C5-critical. convert_latex(latex), digits_to_braille(수표 ⠼ 삽입), frac/sqrt/lim/log/sum/sup/sub
│   │   ├── text_braille.py · formula_braille.py · table_braille.py · image_braille.py · cartoon_braille.py · chart_graph_braille.py
│   │   │   table_braille: _render_grid / _render_linear (render_mode별 표 조판)
│   │   └── layout_braille.py PART 10 조판 본체. layout(braille, page_no, job_id, *, layout_result, llm_outputs)→line_overflow_rate. reading_order정렬·_break_line(32칸 단어경계+first_width 들여예약, 강제분리 카운트)·heading 빈줄(L1 2/1·L2 1/1·L3 1/0)·1단계 제목 가운데정렬·3·4단계 5칸·문단 3칸들여(text)·목록 3칸들여(list_item, tier추론X)·페이지행(원본번호 좌[page_number]·꼬리말 가운데[header_footer]·점자번호 우, 한 원본→여러 점자페이지 시 2번째부터 알파벳 접두 a,b,c)·_paginate(25줄,페이지첫줄 빈줄버림)·_save. 조판 rule_trail(heading_blank·line_wrap·indent)을 점자 좌표로 BrailleOutput.rule_trail에 emit(braille_text_list 귀속). 마커/글상자 헬퍼(BBPG 정본). ⚠촉각그래픽(table/chart SVG)·출전(citation 신호없음)·원본 페이지 변경선(여러 원본→한 점자페이지 중간 대시선, 콘텐츠 흐름 속 경계위치 메타 필요) 미배선
│   ├── quality/                 # PART 11 — ⚠ 미구현 스텁 (TODO 단계4)
│   │   ├── quality_checker.py   QualityChecker.check() 주석만 — 미구현
│   │   └── metrics_collector.py MetricsCollector 주석만 — 미구현
│   └── (각 폴더 __init__.py)
├── utils/
│   ├── file_merger.py   PART 10 후반. 페이지별 결과 → output/result.brf, result.txt 병합
│   └── logger.py        get_logger(name), setup_root_logging()
├── protos/
│   ├── braille_service.proto        BE↔AI 계약 (= ../../plan/braille_service.proto.txt)
│   ├── formulanet_service.proto     AI↔FormulaNet
│   ├── build.sh                     protoc 생성 스크립트
│   └── generated/                   braille_service_pb2(_grpc).py, formulanet_service_pb2(_grpc).py (직접 수정 금지)
├── test/                            상세 → test/.claude/CLAUDE.md
├── requirements.txt / requirements-ai.txt (GPU용, braillify 포함)
├── docker-compose.yml (TimescaleDB + ChromaDB + formulanet) · setup.sh · pytest.ini · .env(.example)
```

---

## 실행 흐름 (pipeline.py — 가장 먼저 볼 파일)

`run(task)` → `asyncio.wait_for(_run_pipeline, timeout=180)`. **현주↔태민 경계는 파일**:
`storage/jobs/{job}/temp/page_{no:03d}/data/{no:03d}_txt_result.json`
형식 `{meta:{job_id,page_no,extraction_method}, elements:[{id,order,type,content}]}` (현주 산출 형식 = `../../step3_hyunju_output.md`).

- **mode a/c — Phase 1 (현주 추출)**: 경계 파일이 **없으면** `_extract_with_hyunju` 실행 → ZERO는 `analyze_pdf` PyMuPDF 텍스트를 `_blocks_from_text`로 요소화(`extraction_method=TEXT_NATIVE`), non-ZERO는 `_extract_via_models`(QwenLayout/YOLO/QwenOCR, 모델 미탑재 시 빈 결과로 격리, `OCR`) → `data/NNN_txt_result.json` 기록. 파일이 **이미 있으면 그대로 사용**(현주가 별도 생성한 핸드오프).
- **mode a/c — Phase 2 (태민)**: `_read_txt_result` → `_parse_txt_result`(id→element_id, order→reading_order, content→corrected_text/formula는 latex_string, `chart`→`chart_graph` 매핑) → 타입별 **6-체인 `asyncio.gather(return_exceptions=True)`**(`_run_*_chain`은 opt→braille만, 현주 OCR 없음) → 각 단계 json 기록(`type/{type}/*_ocr|cap, *_opt, *_braille.json`) → `LayoutBraille.layout` → `_build_response`.
- **mode b**: source_text → text 체인(opt→braille) → `LayoutBraille.layout` → `_build_response`.
- routing_tier: doc_meta 있으면 그 값, 없으면(주입 파일) `extraction_method`로 유추(TEXT_NATIVE→ZERO). ZERO/`ocr_confidence==1.0`이면 opt가 모델 없이 passthrough → GPU 불필요.
- 타임아웃 → C7 BLOCKED, 예외 → C1 BLOCKED. `_debug_dump`(APP_ENV=debug): `02_doc_meta`·`04_all_ocr`·`05_all_opt`.

`grpc_server._build_proto_response(dict)`가 pipeline dict → BrailleResponse proto로 변환.

> step3 범위: text·formula 체인 E2E 동작. 시각자료(table/image/cartoon/chart_graph)는 경계 파일에 해당 요소가 있으면 체인이 돌지만 캡셔닝(현주 PART*-1)·classifier는 미구현(step4).

---

## 데이터 모델 요지 (schemas/)

- **PageTask**(task.py): job_id, page_no, total_pages, pdf_data, mode(a/b/c), source_text. `from_proto`에서 mode 소문자화·기본 "c".
- **BBoxItem**(layout.py): element_id(UUID 자동), type(str), bbox(tuple x1,y1,x2,y2), reading_order, heading_level?, caption_ref?, flags[]. *코드 주석은 type을 "11종"으로 표기(text/title/caption/table/image/formula/list_item/header_footer/page_number/footnote/sidebar) — cartoon/chart_graph는 classifier가 type을 갱신.*
- **DocumentMeta**(layout.py): pdf_confidence, routing_tier(ZERO/STANDARD/QUALITY), scan_only, page_image_path?, header/footer_pattern?.
- **ExtractedContent**(content.py): element_id, corrected_text?, latex_string?, ocr_confidence, visual_subtype?, subtype_confidence?, table_structure?, flags[]. (OCR·전처리·분류 공통)
- **LLMOutput**(content.py): element_id, corrected_text, render_mode(text_only|table_grid|transposed|linear|narrative|formula_block|formula_inline), tn_text?, routing_tier, processing_time_ms, rule_trail[].
- **BrailleOutput**(content.py): element_id, braille_lines[], rule_trail[].
- **QualityReport**(quality.py): page_id, status, ocr_confidence_avg, line_overflow_rate, critical_errors[], review_flags[].

---

## 핵심 불변 규칙

1. **빈 결과 금지**: 실패 시 `[처리 불가: {사유}]` 플레이스홀더. pipeline의 `_placeholder_extracted`가 표준.
2. **rule_trail 필수**: 점자 출력에 `{rule_id, source, section, title, excerpt, priority}` 기록.
3. **요소 단위 격리**: 6-체인은 반드시 `asyncio.gather(return_exceptions=True)`. 한 요소 실패가 페이지를 막지 않음.
4. **C5 배포 블로커**: 아라비아 숫자는 수표(⠼) 없이 점형 시작 불가. 로직은 `kor_math_rules.digits_to_braille`/`_num_replace`(`_NUMBER_INDICATOR="⠼"`). **런타임 스캐너는 없고** `test/unit_test/braille/test_rule_engine.py` 전수 통과로만 강제 → 통과 못 하면 배포 차단.
5. **2-GPU 정적 배치**: VRAM Swap 코드 금지. `model_manager.load_all` 1회 로드 후 상주. GPU0=Qwen3-VL+YOLO+TableFormer, GPU1=HyperCLOVA X.
6. **이미지 캡셔닝=GPT-4o**: image/cartoon/chart_graph 캡셔닝(7/8/9-1)은 GPT-4o. Qwen3-VL로 캡셔닝 금지(레이아웃·OCR 전담).
7. **Pydantic v2**: `.model_dump()`/`.model_validate()` 사용. `.dict()` 금지.
8. **braillify 주의**: `substitute_symbols()` 결과의 점자 Unicode(U+2800–U+28FF)를 braillify에 직접 넘기면 이중 변환. `_emit_mixed`로 세그먼트 분리 필수. braillify 2.0.0은 `\x00`·PUA·em dash(—) 거부 → 플레이스홀더 방식 금지.

---

## ⚠ plan 대비 코드 변경 필요 / 미구현 (plan이 정본)

코드가 plan과 어긋나거나 미구현인 부분. **plan이 정본**이므로 아래는 "코드를 이렇게 고쳐야 한다"는 목록이다.

**A. 수정 완료 (2026-05-29)**
1. ✅ **bounding_box 좌표**: `_build_response`가 이제 `{"x","y","x2","y2"}` 키로 내보냄(proto 일치). (단, 현재 경계 파일에 bbox가 없어 값은 0,0,0,0)
2. ✅ **QualityReport.status 표기**: `quality.py` 주석 `COMPLETED|NEEDS_REVIEW|BLOCKED`로 정정.
6'. ✅ **현주 파일 소비 + 단계별 json 기록**: pipeline이 `data/NNN_txt_result.json`을 생성(현주 ZERO)·소비(태민)하고 `type/{type}/*_ocr|cap·*_opt·*_braille.json`을 기록(위 실행 흐름). 차트 파일명은 `cg_*.json`(plan 일치).

**B. 미구현 stub (plan 기준 구현 필요)**
3. **PART 3-4 분류기**: `captioning/classifier.py` = `# TODO [단계3]` 스텁. `ImageClassifier.classify` 부재 → pipeline이 `ImportError` catch → image 고정, cartoon/chart_graph 미분류, visual_subtype/subtype_confidence 미생성. → plan §3-1 값으로 구현.
4. **PART 11 품질검사**: `quality/quality_checker.py`·`metrics_collector.py` 스텁. pipeline이 status **하드코딩 "COMPLETED"**, QualityReport 빈 값. C/R 판정·status 분기·TimescaleDB 기록 전무. → plan §4-1 status 규칙·C1~C7/R1~R12 구현 후 pipeline 연결.
5. **현주 파트(모델 의존)**: layout/ocr/captioning 일부 모델 미탑재 시 동작 안 함. pipeline이 `ImportError/AttributeError`로 격리 → `[처리 불가]` 플레이스홀더.

**C. 남은 정합 (참고)**
7. **테스트 목 `chart_graph_cap.json`**: 런타임 코드는 `cg_cap.json` 기록(plan 일치)하나, `test_data/page_001/type/chart_graph/`의 목 파일명은 `chart_graph_cap.json`으로 남아 있음. step4 시각 테스트 정비 시 통일.

**D. 참고 (충돌 아님)**
8. **TLS 기본 on**: `config.tls_enabled=True` → `serve()`가 인증서 로드. 로컬은 `.env`에서 `TLS_ENABLED=false`.
9. **요소유형 11 vs 13**: BBoxItem 주석 "11종"은 PART3 *초기 감지* 집합. PART3-4 후 cartoon/chart_graph 확정 → 최종 13종(plan §3-1). 주석에 "분류 후 13종" 명시 권장.

> plan(`../../plan/`)과 코드가 다르면 plan을 정본으로 코드를 맞춘다. (이 디렉토리는 model_manager/health_check가 이미 존재 — plan STEP2 산출물 선반영.)

---

## 실행 명령 (작업 디렉토리 = `code/AI/`)

```bash
bash setup.sh                          # 최초 환경 설정
cp .env.example .env                   # TLS_ENABLED=false 로컬 권장
docker compose up -d                   # TimescaleDB + ChromaDB + formulanet
python -m app.core.main                # 서버 기동 (gRPC 50051 + REST 8080)
bash protos/build.sh                   # proto 재생성

# 테스트 (braillify 미설치 시 폴백 모드 — 약자·약어 미지원)
pytest test/unit_test/ -q --tb=short
pytest test/unit_test/braille/test_rule_engine.py -v   # ★ C5 배포 블로커
pytest test/integration/test_grpc_pipeline.py -v
python test/local_runner.py            # 로컬 E2E

pip install braillify                   # 운영 점자 엔진 (또는 requirements-ai.txt)
```

상세 테스트 구조는 `test/.claude/CLAUDE.md`, 단계별 구현 지침은 `../prompts/.claude/CLAUDE.md`.
