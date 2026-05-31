# code/AI/test/ — 테스트 코드 · 데이터

> 전역/프로젝트 규칙은 상위 CLAUDE.md들에서 자동 로드. 권위 충돌 시 `../../../plan/` 우선.
> 테스트 작성 방법론(HOW)의 원문은 `../../prompts/test_guide.md`. 이 파일은 **현재 테스트 자산의 위치·범위·상태** 요약.

작업 디렉토리는 `code/AI/`. 테스트 실행도 거기서 한다.

---

## 설정

- `pytest.ini`: `testpaths=test`, `asyncio_mode=auto`, 마커 `integration`/`unit`/`slow`
- `conftest.py`: `sys.path`에 `AI/` 추가(`from app.x import y` 동작), `DUMMY_PNG_BYTES`(1×1 PNG) 제공
- `local_runner.py`: 로컬 E2E 실행 스크립트
- GPU 없이 실행 가능해야 함 → `routing_tier="ZERO"` + `model_manager` patch (test_guide 원칙 3)

---

## 실제 테스트 파일 (현재 존재)

```
test/
├── integration/
│   └── test_grpc_pipeline.py        gRPC E2E (mode a/b/c, C7 타임아웃, 필드 격리)
└── unit_test/
    ├── core/test_health_api.py      GET /health 응답
    ├── preprocessor/test_preprocessor.py   라우팅 티어·confidence
    ├── layout/test_layout_merger.py        IoU 병합·reading_order·caption_ref
    ├── classifier/test_classifier.py       목 인터페이스 + pipeline._TEXT_TYPES 라우팅 검증
    ├── formula/test_formula_pipeline.py     LaTeX 복잡도·검증 + BLEU 근사
    ├── table/test_table_pipeline.py         표 opt→braille (GriTS 구조 불변량)
    ├── image/test_image_pipeline.py         이미지 opt→braille (<7초 타이밍)
    ├── cartoon/test_cartoon_pipeline.py     만화 opt→braille
    ├── chart_graph/test_cg_pipeline.py      차트 opt→braille
    ├── chart_graph/test_few_shot_opt.py     few-shot 프롬프트 opt 검증
    ├── braille/test_rule_engine.py          ★ C5 배포 블로커 (수표 ⠼ 전수)
    ├── braille/test_regulation_examples.py  규정 조항별 예시 변환
    ├── braille/test_word_accuracy.py        단어 점자 정확도 (word_pairs.json)
    ├── braille/test_mixed_input.py          텍스트+수식 혼합
    ├── braille/test_layout_braille.py       32칸×25줄 조판
    ├── quality/test_quality_checker.py      ⚠ skip (단계4 미구현)
    ├── quality/test_metrics_collector.py    ⚠ skip (단계4 미구현)
    ├── format/test_extracted_content.py     ExtractedContent 직렬화
    ├── format/test_llm_output.py            LLMOutput 직렬화
    ├── format/test_braille_output.py        BrailleOutput 직렬화
    └── pipeline/test_step3_e2e.py           텍스트/수식 체인 E2E + 6체인 격리(레벨 A+B)
```

> `unit_test/text/` 폴더는 **없다** — 텍스트 검증은 braille/(word_accuracy, mixed_input)와 pipeline/에 분산. (plan `디렉토리 구조.md`는 text/test_text_pipeline.py를 적었으나 코드엔 없음.)

---

## 테스트 데이터 (`test/test_data/`)

| 파일/폴더 | 용도 |
|---|---|
| `page_001/` | 현주 파트 미구현 대체 목 페이지. `layout/merged_layout.json` + `type/{text,formula,table,image,cartoon,chart_graph}/*.json` (ExtractedContent[] 형식) |
| `regulation_pairs/section_01~14_*.json` | 규정 조항별 입력→기대출력 쌍 (수동 기록, 순환검증 방지) |
| `word_pairs.json` | 한국어 단어 → 점자 기대값 |
| `formula_pairs.json` | LaTeX → 점자 기대값 (BLEU 근사) |
| `mixed_pairs.json` | 텍스트+수식 혼합 → 점자 기대값 |
| `braille_translation_samples.json` | 점역 샘플 |
| `classifier_test_set.json` | 분류기 인터페이스 명세 |
| `bbpg_layout_rules.json` | 조판/레이아웃 규칙 데이터(BBPG 제1·2장 정본). 폐기된 JAJAK 기반 `jajak_layout_rules.json` 대체 |
| `few_shot_examples.json` | LLM few-shot 예시 |
| `testdata_complex.txt` | **태깅 규약 정본 예시쌍**(태민 작성). 점역 직전 태그 텍스트(```` ``` ```` 블록) ↔ 기대 점자(`<aside>`)를 복합 시각자료별로 수록. 인라인 태그 `<!이름>`/`<!/이름>` 형식·점역자주 `⠠⠄`·테두리 등 정본 plan §3-5의 근거 데이터. ⚠ 입력 텍스트는 32칸 조판 이전 상태. |

> `page_001/type/chart_graph/chart_graph_cap.json` — 목 데이터는 `chart_graph_cap.json`을 쓰지만, **plan 런타임 파일명은 `cg_cap.json`**(plan 데이터파이프라인 §7). 정본은 plan의 `cg_*.json` → 코드/테스트 정합 시 통일 필요.

---

## 테스트 원칙 (test_guide.md 요약)

1. **순환 검증 금지**: 기대값을 생산 코드(`translate_tagged_text` 등)로 만들지 말 것. 규정에서 수동 도출해 JSON에 직접 기록.
2. **목 데이터 패턴**: 현주 파트(TableCap/ImageCap/CartoonCap/ChartGraphCap/ImageClassifier) 미구현 → `test_data/`에 출력형식 JSON 목으로 대체.
3. **ZERO 티어 GPU-free**: `routing_tier="ZERO"` + `patch("...model_manager")`로 모델 없이 단위 테스트.
4. **6체인 격리 2레벨**: (A) `asyncio.gather(return_exceptions=True)` stdlib 동작, (B) `patch.object(pipeline, "_run_formula_chain", fail)` 후 `_run_pipeline` 통합 — 둘 다 작성.
5. **정확도 측정**: GriTS(표 구조 불변량, >0.88), BLEU 근사(수식 char-level F1, ≥0.88). 둘 다 비순환.

테스트 클래스 분리 규약(`TestXxxPipelineBasic`/`TestGriTS`/`TestBLEU`/`TestXxxRenderModes`/`TestXxxTNContent`/`TestXxxTiming`)은 test_guide.md 참조.

---

## 실행

```bash
pytest test/unit_test/ -q --tb=short                       # 전체 단위
pytest test/unit_test/braille/test_rule_engine.py -v       # ★ C5 배포 블로커 (전수 통과 필수)
pytest test/integration/test_grpc_pipeline.py -v           # gRPC E2E (서버 기동)
pytest -m "not slow" -q                                    # 모델 로드 없는 것만
python test/local_runner.py                                # 로컬 E2E
```

- braillify 미설치 시 폴백 모드(약자·약어 미지원)로 동작 — 일부 정확도 테스트 영향.
- `quality/` 테스트는 현재 `pytest.mark.skip` (PART 11 미구현).

---

## ⚠ plan 대비 상태

- **품질(PART 11) 테스트 skip**: `quality_checker.py`/`metrics_collector.py` 스텁이라 테스트도 skip. plan 기준 단계4(=plan STEP5)에서 활성화.
- **분류기 테스트는 인터페이스 검증만**: `classifier.py` 스텁이라 실제 분류 정확도(≥90%, plan)는 미검증. 목 인터페이스 + `pipeline._TEXT_TYPES` 라우팅만 확인.
- **파일명 정합**: `chart_graph_cap.json`(목) vs `cg_cap.json`(plan 런타임) 불일치 — plan 우선 통일 대상.
