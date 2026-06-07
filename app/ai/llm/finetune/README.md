# 점역 최적화 LLM 파인튜닝 (T5-4 스켈레톤)

HyperCLOVA X 점역 최적화(PART 4-2~9-2)를 위한 LoRA SFT 골격이다.
**현재는 스켈레톤** — 데이터 로드·시드 고정·LoRA/Trainer 설정 자리만 있고, 실제 학습 루프는
`train.run()`에서 `NotImplementedError`로 막혀 있다. GPU·하이퍼파라미터·데이터 규모를 인프라
담당과 확정한 뒤 `train.py`의 주석 블록을 구현한다.

## 구성

| 파일 | 역할 |
|---|---|
| `data_format.py` | `TrainingExample` 스키마 + JSONL 입출력(`to_jsonl`/`from_jsonl`) |
| `dataset.py` | 프롬프트 빌드(추론과 동일 템플릿) + SFT chat 쌍 + `set_seed` |
| `train.py` | LoRA SFT 학습 스크립트 스켈레톤 (`LoRAConfig`/`TrainConfig`/`run`/`main`) |

## 데이터 포맷 (JSONL, 한 줄 = 한 예시)

```json
{"element_type": "chart_graph", "input_text": "연도별 발행 권수 막대그래프. 2020년 980권 …", "target_text": "[점역사주] 막대그래프: 연도별 발행 권수. 2020년: 980권 …", "source": "과학3-1, p.48", "tier": "QUALITY"}
```

- `element_type`: `text` / `formula` / `table` / `image` / `cartoon` / `chart_graph`
- `input_text`: 프롬프트에 들어갈 입력 (OCR 텍스트 · GPT-4o 캡션 · LaTeX)
- `target_text`: **점역사가 작성·승인한 정답** (모델 출력 자가학습 금지 — 순환 학습 방지)
- 프롬프트는 추론과 동일한 opt 템플릿(`_PROMPT*`)을 재사용하므로, 프롬프트를 고치면 학습 데이터도
  자동 반영된다.

## 실행 (스켈레톤)

```bash
# 데이터 로드·시드까지 수행 후 NotImplementedError (학습 루프 미구현)
python -m app.ai.llm.finetune.train --data data/sft_train.jsonl --out runs/braille-lora
```

## 데이터셋 수집 경로 · 라이선스 (TODO — 인프라/법무 협의)

- **수집원**: 점역사가 검수한 점역 결과(T5-1 데모셋 + 운영 누적 교정본). `source` 필드에 교과서·페이지를
  기록해 출처를 추적한다.
- **라이선스**: 교과서 원문은 저작권 보호 대상 — 학습 사용 가능 범위를 출판사/발주처와 확인 필요.
  공개 배포 불가 데이터는 사내 스토리지에만 보관하고 리포지토리에 커밋하지 않는다(`.gitignore`).
- **개인정보**: 학생 이름 등 PII가 캡션/OCR에 섞이지 않도록 수집 단계에서 마스킹.

## 의존성 (학습 시점에 설치 — 현재 미설치 무방)

`torch`, `transformers`, `peft`, `trl`, `datasets`. `train.py`는 이들을 함수 안에서 지연 import하므로
스켈레톤·테스트는 GPU 라이브러리 없이 동작한다.
