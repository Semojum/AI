# Semojum (V2)

한국 점자(BRF) 초안을 자동 생성하는 AI 서버. 점역사(인간 번역가)가 검토·수정하는 초안을 제공한다.

**시스템 연결**: Spring Boot BE → gRPC (port 50051) → **Python AI Server** → gRPC (port 50052) → FormulaNet Docker

---

## 개발 단계 현황

| STEP | 상태 | 기한 | 내용 |
|---|---|---|---|
| 1 | ✅ 완료 | ~05.15 | 설계 (데이터 파이프라인, 기술 명세) |
| 2 | 🔄 진행 중 | ~05.17 | AI-BE gRPC 통신 + 상태 확인 API |
| 3 | 🔄 진행 중 | ~05.24 | 텍스트 문서 파이프라인 (전처리→OCR→점역) |
| 4 | ⏳ 예정 | ~05.31 | 복합 문서 파이프라인 (수식·표·이미지·캡셔닝) |
| 5 | ⏳ 예정 | ~06.07 | 프롬프트 엔지니어링 + 파인튜닝 스켈레톤 |

---

## 빠른 시작

```bash
# 1. 환경 초기화 (venv 생성, 패키지 설치, proto 빌드)
bash setup.sh

# 2. 환경 변수 설정
cp .env.example .env
vi .env  # 모델 경로, DB URL 등 입력

# 3. 인프라 서비스 기동 (TimescaleDB, ChromaDB)
docker compose up -d

# 4. AI 서버 실행
source venv/bin/activate
python -m app.core.main
```

서버가 뜨면 `GET http://localhost:8080/health` 로 상태를 확인한다.

---

## 아키텍처

### 처리 파이프라인

```
BrailleRequest (job_id, page_no, pdf_data, mode a|b|c)
  PART 1   전처리 (pdf_analyzer)     → DocumentMeta, 라우팅 티어 결정
           ZERO (≥0.92): PyMuPDF 텍스트 직접 추출
           STANDARD (0.30–0.92): 전체 VLM 파이프라인
           QUALITY (<0.30): GPT 폴백
  PART 2   레이아웃 감지 (qwen_layout + yolo_layout → layout_merger)
  PART 3   병렬 처리
           3-1 텍스트 OCR     (qwen_ocr)
           3-2 수식 OCR       (formula_ocr → FormulaNet gRPC)
           3-3 표 추출        (table_cap → Docling TableFormer)
           3-4 이미지 분류    (classifier → Qwen3-VL)
  PART 4   캡셔닝             (captioning/)
  PART 5   점역 최적화        (llm/ → HyperCLOVA X)
  PART 6   시맨틱 태깅 + 점역 (braille/)
  PART 7   촉각 그래픽        (Canny Edge → ASCII + SVG)
  PART 8   조판               (layout_braille → 32칸×25줄)
  PART 9   품질 검사          (quality_checker → C1-C7 / R1-R12)
           → BrailleResponse (COMPLETED | NEEDS_REVIEW | BLOCKED)
```

**하드 타임아웃**: `asyncio.wait_for()` 180초 (C7 오류)

### gRPC 요청 모드

| 모드 | 입력 | 출력 |
|---|---|---|
| `a` | PDF 이미지 | bbox + 교정 텍스트 + rule_trail |
| `b` | 텍스트 | 점자 BRF |
| `c` | PDF 이미지 | 점자 BRF + 촉각 그래픽 + 품질 보고서 |

### 모델 구성 (L4 GPU 24GB × 2)

| 모델 | 역할 |
|---|---|
| Qwen3-VL-8B INT4 AWQ | 레이아웃 감지, OCR, 이미지 분류, 캡셔닝 |
| HyperCLOVA X SEED Think 14B INT4 | 점역 최적화 (PART 5) |
| DocLayout-YOLO v2 | 보조 레이아웃 감지 |
| Docling TableFormer BF16 | 표 구조 추출 |
| PP-FormulaNet (Docker) | 수식 OCR (내부 gRPC) |
| GPT-4o / GPT-5.x | 캡셔닝 폴백 (목표 사용률 <15%) |

---

## 테스트

```bash
# 전체 단위 테스트 (GPU 불필요)
pytest test/unit_test/ -q --tb=short

# 개별 테스트
pytest test/unit_test/core/test_health_api.py -v        # Health API
pytest test/unit_test/braille/test_rule_engine.py -v    # C5 수표 배포 블로커
pytest test/unit_test/braille/test_layout_braille.py -v # 32칸×25줄 조판
pytest test/unit_test/layout/test_layout_merger.py -v   # IoU 병합·reading_order
pytest test/unit_test/preprocessor/test_preprocessor.py -v  # 라우팅 티어

# gRPC E2E 통합 테스트 (서버 기동 후 실행)
pytest test/integration/test_grpc_pipeline.py -v

# 로컬 단일 페이지 테스트
python test/local_runner.py --image page.png --mode c
```

> **C5 배포 블로커**: `test_rule_engine.py` 32개 테스트가 모두 통과해야 배포 가능.

---

## 환경 변수 (.env)

| 변수 | 기본값 | 설명 |
|---|---|---|
| `APP_ENV` | `production` | `debug` 시 각 PART 완료 후 JSON 덤프 저장 |
| `GRPC_PORT` | `50051` | BE↔AI gRPC 포트 |
| `REST_PORT` | `8080` | 헬스체크 REST 포트 |
| `PAGE_TIMEOUT_SECONDS` | `180` | 페이지당 처리 타임아웃 |
| `QWEN3_VL_MODEL_PATH` | `/models/qwen3-vl-8b-awq` | Qwen3-VL 모델 경로 |
| `HCXT_MODEL_PATH` | `/models/hyperclovax-seed-think-14b` | HyperCLOVA X 모델 경로 |
| `FORMULANET_SERVICE_ADDR` | `localhost:50052` | FormulaNet gRPC 주소 |
| `OPENAI_API_KEY` | — | GPT 폴백용 API 키 |

---

## REST API

| 엔드포인트 | 설명 |
|---|---|
| `GET /health` | 서버 상태, 포트, 모델 로드 상태 |
| `GET /models/status` | 모델별 로드 상태 상세 |

---

## 품질 기준

**Critical 오류 (C1–C7)** — 해당 요소 차단, 플레이스홀더 삽입:
- **C1**: 전체 페이지 OCR 실패 → `BLOCKED`
- **C3**: 수식 파싱 실패 → `[수식 재확인 필요]`
- **C5**: 점자 숫자 오류 → **배포 블로커**
- **C6**: 32칸 초과 >30% → `NEEDS_REVIEW`
- **C7**: 180초 타임아웃 → `BLOCKED`

**Review 플래그 (R1–R12)** — 페이지 `NEEDS_REVIEW` 표시, 내용 차단 없음.

---

## proto 재빌드

```bash
bash protos/build.sh
```

생성 파일(`protos/generated/`)은 `.gitignore`로 제외되어 있으므로 서버 환경에서 반드시 실행해야 한다.

---

## 디버그 모드

```bash
APP_ENV=debug python -m app.core.main
```

각 PART 완료 시 `storage/jobs/{job_id}/temp/page_{no}/` 하위에 Pydantic JSON이 저장된다.
