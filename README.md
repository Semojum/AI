# Semojum V2 AI Server

AI 점자 번역 파이프라인 — gRPC 기반 페이지 단위 처리

---

## 빠른 시작

```bash
# 1. 환경 초기화 (venv 생성, 패키지 설치, proto 빌드)
bash setup.sh

# 2. .env 값 설정
vi .env

# 3. 인프라 서비스 기동 (TimescaleDB, ChromaDB)
docker compose up -d

# 4. AI 서버 실행
source venv/bin/activate
python -m app.core.main
```

---

## 개발 단계 현황

| 단계 | 상태 | 내용 |
|---|---|---|
| **단계 1** (파랑) | ✅ 구현 완료 | gRPC 통신 기반, 더미 파이프라인, 타임아웃 래퍼 |
| **단계 2** (초록) | 대기 | 전처리, 레이아웃, OCR, 점자 변환, 포맷팅 |
| **단계 3** (보라) | 대기 | 수식/표/이미지, 캡셔닝, 촉각 그래픽 |
| **단계 4** (주황) | 대기 | 품질 검증 C1~C7, RAG, 메트릭 수집 |
| **단계 5** (빨강) | 대기 | A100 전환, Qwen-32B, HyperCLOVA X 14B FP16 |

---

## 테스트

```bash
# 통합 테스트 (서버 기동 후)
pytest test/integration/test_grpc_pipeline.py -v

# 타임아웃 로직 단위 테스트 (서버 불필요)
pytest test/integration/test_grpc_pipeline.py::TestTimeout -v

# 로컬 단일 이미지 테스트
python test/local_runner.py --image page.png --mode c
```

---

## 프로젝트 구조

```
AI/
├── protos/
│   ├── braille_service.proto   # gRPC 서비스 정의
│   ├── build.sh                # proto 빌드 스크립트
│   └── generated/              # protoc 자동 생성 (setup.sh 실행 후 생성)
├── app/
│   ├── schemas/                # Pydantic v2 내부 스키마
│   ├── core/
│   │   ├── config.py           # 환경 설정
│   │   ├── main.py             # 서버 진입점
│   │   ├── grpc_server.py      # gRPC 서버 (PART 0)
│   │   ├── pipeline.py         # 파이프라인 진입점 (PART 1~9)
│   │   └── routes.py           # REST (헬스체크만)
│   └── utils/
│       └── logger.py
├── test/
│   ├── local_runner.py
│   └── integration/
│       └── test_grpc_pipeline.py
├── docker-compose.yml
├── requirements.txt
├── setup.sh
└── .env.example
```

---

## proto 재빌드

proto 파일 수정 후:

```bash
bash protos/build.sh
```
