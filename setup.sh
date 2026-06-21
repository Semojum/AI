#!/bin/bash

# =================================================================
# Semojum V2 AI — Server Setup Script
# 환경: Ubuntu 22.04 LTS (jammy) / Python 3.10 / CUDA 12.1
# 기본 이미지: GCP 민짜 Ubuntu 22.04 LTS (Deep Learning 이미지 아님).
#             → NVIDIA 드라이버가 미설치이므로 이 스크립트가 직접 설치한다.
#               (DL 이미지를 쓰면 Py3.12/CUDA12.9가 고정되므로 민짜 이미지 채택)
# 로컬 개발: WSL2(Ubuntu)는 호스트 Windows의 NVIDIA 드라이버를 공유하므로
#           드라이버 설치 단계가 자동 skip된다(nvidia-smi 이미 동작).
# 기본 대상: NVIDIA L4 GPU (24GB VRAM) × 2  [단계 1~4]
# 단계 5 환경: L4 × 1 + A100 × 1 (80GB) — 모델 업그레이드 필요
#
# L4 기준 모델 선정 (단계 1~4):
#   Stage A (VLM)  : Qwen3-VL-8B INT4 AWQ  (~5-6 GB VRAM)
#   Stage B (LLM)  : HyperCLOVA X SEED Think 14B INT4 (~8 GB VRAM)
#   보조 탐지      : DocLayout-YOLO v2 FP32, Docling TableFormer BF16
#   수식 OCR       : PP-FormulaNet (PaddlePaddle Docker, 별도)
#   → L4 24GB: Stage A/B 동시 로드 불가 → VRAM Swap 필요 (2~4초)
#
# 단계 5 모델 업그레이드 (A100 80GB, VRAM Swap 불필요):
#   Stage A : Qwen3-VL-32B INT4 AWQ
#   Stage B : HyperCLOVA X SEED Think 14B FP16
# =================================================================

set -e

echo "========================================="
echo "  Semojum V2 AI Setup (CUDA 12.1 / L4)  "
echo "========================================="

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# -------------------------------------------------------------------
# 0. [GPU] L4 GPU 환경 검증
#    단계 1~4 기준: L4 (24GB) 필요.
#    단계 5에서 A100 전환 시 STAGE=5 환경변수를 설정하여 경고 우회.
# -------------------------------------------------------------------
STAGE=${STAGE:-1}
if command -v nvidia-smi &> /dev/null; then
    GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "UNKNOWN")
    GPU_MEM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0")
    echo "🖥️  GPU 감지: $GPU_NAME  (VRAM: ${GPU_MEM_MB} MiB)"
    if [ "$STAGE" -lt "5" ] && [ "$GPU_MEM_MB" -lt "10000" ]; then
        echo "   [경고] VRAM ${GPU_MEM_MB}MiB < 10GB — L4(24GB) 환경에서 HyperCLOVA X 14B INT4 실행 권장"
        echo "          단계 1 더미 파이프라인은 GPU 없이도 동작합니다."
    fi
else
    echo "   [경고] nvidia-smi 없음 — NVIDIA 드라이버 미설치 상태."
    if command -v apt-get &> /dev/null; then
        # GCP 민짜 Ubuntu 22.04 이미지: 드라이버가 없으므로 직접 설치한다.
        # (WSL2 는 호스트 드라이버를 공유 → nvidia-smi 가 이미 동작하여 이 블록 skip)
        echo "   - 민짜 Ubuntu 감지 → NVIDIA 드라이버(535-server, L4/Ada 호환) 설치 시도..."
        sudo apt-get update -qq
        sudo apt-get install -y ubuntu-drivers-common
        sudo ubuntu-drivers install --gpgpu nvidia:535-server 2>/dev/null \
            || sudo apt-get install -y nvidia-driver-535-server \
            || echo "   [경고] 드라이버 자동설치 실패 — 'sudo ubuntu-drivers install' 수동 실행 필요"
        echo "   ────────────────────────────────────────────────────────────"
        echo "   [중요] 드라이버 설치 후 재부팅이 필요할 수 있습니다:"
        echo "          sudo reboot  →  재부팅 후 'bash setup.sh' 재실행"
        echo "          (nvidia-smi 가 정상 동작하면 재부팅 불필요)"
        echo "   ────────────────────────────────────────────────────────────"
    else
        echo "          GPU 없이도 단계 1 더미 파이프라인은 동작합니다."
    fi
fi

# -------------------------------------------------------------------
# 1. [System] CUDA Toolkit 12.1 설치
#    NVIDIA 드라이버는 위 단계 0 에서 설치(민짜 이미지) 또는 호스트 공유(WSL).
#    여기서는 535-server 드라이버와 호환되는 CUDA 12.1 "툴킷"만 설치한다
#    (cuda-toolkit-12-1 메타패키지는 드라이버를 끌어오지 않음).
# -------------------------------------------------------------------
echo "📦 [1/9] Checking CUDA Toolkit 12.1..."

if ! command -v nvcc &> /dev/null || [[ $(nvcc --version 2>/dev/null) != *"release 12.1"* ]]; then
    echo "   - CUDA Toolkit 12.1 설치 중..."
    sudo apt-get update -qq
    sudo apt-get install -y wget gnupg software-properties-common

    wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-ubuntu2204.pin
    sudo mv cuda-ubuntu2204.pin /etc/apt/preferences.d/cuda-repository-pin-600

    wget -q https://developer.download.nvidia.com/compute/cuda/12.1.0/local_installers/cuda-repo-ubuntu2204-12-1-local_12.1.0-530.30.02-1_amd64.deb
    sudo dpkg -i cuda-repo-ubuntu2204-12-1-local_12.1.0-530.30.02-1_amd64.deb
    sudo cp /var/cuda-repo-ubuntu2204-12-1-local/cuda-*-keyring.gpg /usr/share/keyrings/
    sudo apt-get update -qq
    # 드라이버는 건드리지 않고 툴킷만 설치
    sudo apt-get install -y cuda-toolkit-12-1

    echo 'export PATH=/usr/local/cuda-12.1/bin:$PATH' >> ~/.bashrc
    echo 'export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
    export PATH=/usr/local/cuda-12.1/bin:$PATH
    export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH

    rm -f cuda-repo-ubuntu2204-12-1-local_12.1.0-530.30.02-1_amd64.deb
    echo "   - CUDA 12.1 설치 완료."
else
    echo "   - CUDA 12.1 already installed."
    export PATH=/usr/local/cuda-12.1/bin:$PATH
    export LD_LIBRARY_PATH=/usr/local/cuda-12.1/lib64:$LD_LIBRARY_PATH
fi

export CUDA_HOME=/usr/local/cuda-12.1

# -------------------------------------------------------------------
# 2. [System] 필수 시스템 패키지 설치
#    liblouis: 점자 변환 엔진 (louis Python 바인딩 의존)
#    poppler-utils: PDF 처리 보조
#    libgl1-mesa-glx, libgomp1: OpenCV 런타임 의존
# -------------------------------------------------------------------
echo "🔧 [2/9] Installing system packages..."
sudo apt-get install -y \
    python3.10 python3.10-venv python3.10-dev python3-pip \
    build-essential git curl \
    libgl1-mesa-glx libgomp1 \
    liblouis-dev liblouis-bin liblouis-data \
    poppler-utils \
    protobuf-compiler

# -------------------------------------------------------------------
# 3. [Venv] Python 3.10 가상환경 구성
# -------------------------------------------------------------------
echo "🐍 [3/9] Creating Python 3.10 virtual environment..."
if [ -d "$ROOT/venv" ]; then
    echo "   - 기존 venv 재사용 (이미 설치된 패키지는 자동 skip — 재실행 시 빠름)."
    echo "     완전 초기화하려면: rm -rf venv 후 재실행."
else
    python3.10 -m venv "$ROOT/venv"
fi
source "$ROOT/venv/bin/activate"
pip install --upgrade pip setuptools wheel packaging ninja -q

# -------------------------------------------------------------------
# 4. [GPU Core] PyTorch 2.5.1 (cu121)
#    L4 + CUDA 12.1 기준 검증된 버전. V1과 동일.
#    torchvision은 Qwen3-VL image preprocessing에 필요.
# -------------------------------------------------------------------
echo "🔥 [4/9] Installing PyTorch 2.5.1 (cu121)..."
pip install \
    "torch==2.5.1" \
    "torchvision==0.20.1" \
    --index-url https://download.pytorch.org/whl/cu121

# -------------------------------------------------------------------
# 5. [Acceleration] PyTorch SDPA 확인
#    PyTorch 2.5.1 내장 scaled_dot_product_attention 사용.
#    INT4 AWQ 양자화 추론 환경에서 flash-attn 소스 빌드 대비 성능 차이 무시.
#    Qwen3-VL / HyperCLOVA X SEED Think 14B 모두 transformers에서 SDPA 자동 선택.
# -------------------------------------------------------------------
echo "⚡ [5/9] Verifying PyTorch SDPA (built-in, no extra build needed)..."
python -c "
import torch
fa = torch.backends.cuda.flash_sdp_enabled()
ea = torch.backends.cuda.mem_efficient_sdp_enabled()
ms = torch.backends.cuda.math_sdp_enabled()
print(f'   SDPA backends — flash={fa}  efficient={ea}  math={ms}')
assert fa or ea, 'SDPA efficient backend not available — check CUDA/torch install'
"
echo "   - SDPA 확인 완료."

# -------------------------------------------------------------------
# 6. [AI Models] 모델 의존성 패키지 설치
#
#    transformers 4.57.0 — Qwen3-VL 필수 버전 / HyperCLOVA X SEED Think 14B 호환
#                          tokenizers>=0.22.0,<=0.23.0 요구 (4.57.0 의존 범위)
#
#    AutoAWQ 설치 전략:
#      PyPI autoawq 0.2.7 wheel = py3-none-any (순수 Python, CUDA 커널 없음)
#      PyPI wheel의 intel-extension-for-pytorch 의존은 NVIDIA 환경에서 설치 불가.
#      → --no-deps 로 설치 후 NVIDIA 호환 의존성만 수동 설치.
#
#    AutoAWQ Kernels 설치 전략:
#      PyPI autoawq_kernels 휠 = manylinux2014 CPU 전용 (CUDA GEMM 커널 없음).
#      → GitHub Releases 에서 CUDA 12.1 / cp310 전용 휠 직접 설치.
#
#    [주의] numpy<2.0 고정: torch 2.5.x와 numpy 2.x 충돌 방지
# -------------------------------------------------------------------
echo "🧠 [6/9] Installing AI model dependencies..."

# numpy 먼저 고정 설치
pip install "numpy==1.26.4"

# Hugging Face 생태계
pip install \
    "transformers==4.57.0" \
    "tokenizers==0.22.0" \
    "accelerate==1.2.1" \
    "einops==0.8.0" \
    "timm==1.0.11" \
    "safetensors==0.4.5"

# AutoAWQ — IPEX(Intel) 의존 제거, --no-deps 설치 후 NVIDIA 호환 의존성만 수동 설치
echo "   - AutoAWQ 0.2.7 설치 (--no-deps, IPEX 제외)..."
pip install "autoawq==0.2.7" --no-deps
pip install \
    "datasets>=2.16.0" \
    "zstandard>=0.22.0"
# triton은 PyTorch 2.5.1 설치 시 함께 설치됨 (별도 불필요)

# AutoAWQ Kernels — CUDA 12.1 / Python 3.10 전용 휠 (GitHub Releases)
echo "   - AutoAWQ Kernels 0.0.9 설치 (CUDA 12.1 전용 휠)..."
pip install \
    "https://github.com/casper-hansen/AutoAWQ_kernels/releases/download/v0.0.9/autoawq_kernels-0.0.9+cu121-cp310-cp310-linux_x86_64.whl" \
    || echo "   [경고] autoawq_kernels CUDA 휠 설치 실패 — GitHub Release URL 확인 필요"

# Qwen3-VL 전용 유틸 (이미지 전처리 헬퍼)
pip install "qwen-vl-utils>=0.0.8" || echo "   [경고] qwen-vl-utils 설치 실패 — 수동 확인 필요"

# -------------------------------------------------------------------
# 7. [Stage 1] requirements.txt 설치 (gRPC, FastAPI, 이미지 처리 등)
#    Stage 1 gRPC 인프라 구동에 필요한 핵심 패키지만 설치.
#    AI 모델 의존 패키지(transformers, docling, braillify 등)는
#    requirements-ai.txt 로 분리됨 — Stage 2 시작 전 별도 설치 필요.
# -------------------------------------------------------------------
echo "📦 [7/9] Installing requirements.txt (Stage 1 core)..."
pip install -r "$ROOT/requirements.txt"

# numpy 재고정 (다른 패키지가 업그레이드했을 경우 방어)
pip install "numpy==1.26.4" --force-reinstall -q

# -------------------------------------------------------------------
# 8. [Proto] gRPC 스텁 빌드
# -------------------------------------------------------------------
echo "🔌 [8/9] Building gRPC proto stubs..."
mkdir -p "$ROOT/protos/generated"

python -m grpc_tools.protoc \
    -I "$ROOT/protos" \
    --python_out="$ROOT/protos/generated" \
    --grpc_python_out="$ROOT/protos/generated" \
    "$ROOT/protos/braille_service.proto"

# grpcio-tools 생성 파일의 import 경로 수정
GRPC_FILE="$ROOT/protos/generated/braille_service_pb2_grpc.py"
if grep -q "^import braille_service_pb2" "$GRPC_FILE" 2>/dev/null; then
    sed -i 's/^import braille_service_pb2/from protos.generated import braille_service_pb2/' "$GRPC_FILE"
fi

touch "$ROOT/protos/generated/__init__.py"
echo "   - proto 빌드 완료: protos/generated/"

# -------------------------------------------------------------------
# 9. [Model] L4 모델 다운로드 가이드 (단계 2+ 필요)
#    단계 1은 더미 파이프라인 — 실제 모델 불필요.
#    단계 2 시작 전 아래 명령어로 모델을 미리 다운로드해 두어야 한다.
#    모델 크기: Qwen3-VL-8B AWQ ~5 GB, HyperCLOVA X 14B INT4 ~8 GB
#    다운로드 위치: .env의 QWEN3_VL_MODEL_PATH / HCXT_MODEL_PATH 와 일치해야 함.
# -------------------------------------------------------------------
echo "📥 [9/9] L4 모델 다운로드 안내 (단계 2+ 필요)..."

# huggingface_hub CLI 설치 (모델 다운로드 도구)
pip install "huggingface_hub[cli]>=0.26.0" -q

echo ""
echo "── L4 모델 다운로드 명령어 (단계 2 시작 전 실행) ────────────"
echo "   # [Stage A] Qwen3-VL-8B INT4 AWQ — VLM (레이아웃·OCR·분류·캡셔닝)"
echo "   # HuggingFace 모델 ID: 릴리스 확인 후 아래를 업데이트하세요."
echo "   # 예: huggingface-cli download <org>/Qwen3-VL-7B-Instruct-AWQ \\"
echo "   #       --local-dir /models/qwen3-vl-8b-awq"
echo ""
echo "   # [Stage B] HyperCLOVA X SEED Think 14B INT4 — 한국어 LLM (점역 최적화)"
echo "   # 예: huggingface-cli download <org>/HyperCLOVA-X-SEED-Think-14B-Instruct \\"
echo "   #       --local-dir /models/hyperclovax-seed-think-14b"
echo ""
echo "   # [보조] DocLayout-YOLO v2 FP32"
echo "   # 예: huggingface-cli download <org>/doclayout-yolo-v2 \\"
echo "   #       --local-dir /models/doclayout-yolo-v2"
echo ""
echo "   # [보조] Docling TableFormer BF16"
echo "   # 예: huggingface-cli download ds4sd/docling-models \\"
echo "   #       --local-dir /models/docling-tableformer"
echo "──────────────────────────────────────────────────────────────"

# -------------------------------------------------------------------
# 사후 처리
# -------------------------------------------------------------------

# .env 생성
if [ ! -f "$ROOT/.env" ]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "[setup] .env 파일 생성 → 값을 직접 편집하세요."
fi

# storage 디렉토리
mkdir -p "$ROOT/storage/jobs"

# 설치 검증 — 한 항목이 없어도 중단하지 않고 끝까지 리포트 (set +e)
echo ""
echo "── 설치 검증 ──────────────────────────────"
set +e
python -c "import torch; print(f'torch        : {torch.__version__}  CUDA={torch.version.cuda}  GPU={torch.cuda.get_device_name(0) if torch.cuda.is_available() else \"NONE\"}')"
python -c "import transformers; print(f'transformers : {transformers.__version__}')"
python -c "import torch; fa=torch.backends.cuda.flash_sdp_enabled(); print(f'SDPA flash   : {fa}')"
python -c "import grpc; print(f'grpcio       : {grpc.__version__}')"
python -c "import pytest; print(f'pytest       : {pytest.__version__}')"
# ── 선택(없어도 단계 1·텍스트/BE 테스트엔 무관) ──
# autoawq 의 import 이름은 'awq' (패키지명 autoawq ≠ 모듈명). AWQ 양자화 모델 추론 시에만 필요.
python -c "import importlib.metadata as m; print('autoawq      :', m.version('autoawq'), '(import awq)')" \
    || echo "autoawq      : 미설치 (선택 — AWQ 모델 추론 시 필요)"
python -c "import awq_ext" 2>/dev/null && echo "awq_kernels  : OK" \
    || echo "awq_kernels  : 미설치 (선택 — GitHub 휠 404. AWQ GPU 커널, 모델 추론 시 수동 설치)"
python -c "import braillify; print('braillify    : OK')" \
    || echo "braillify    : 미설치 (requirements-ai.txt — 점자 엔진, 미설치 시 폴백 모드)"
python -c "import louis; print('louis        : OK')" \
    || echo "louis        : 미설치 (requirements-ai.txt — liblouis 바인딩)"
set -e
echo "───────────────────────────────────────────"

echo ""
echo "========================================="
echo "Setup Completed!"
echo "   다음 단계:"
echo "   1. .env 파일 편집"
echo "   2. docker compose up -d  (TimescaleDB + ChromaDB)"
echo "   3. python -m app.core.main          (서버 기동)"
echo "   4. pytest test/integration/ -v      (단계 1 통합 테스트)"
echo ""
echo "   단계 2 시작 전:"
echo "   5. pip install -r requirements-ai.txt   (AI 모델 의존 패키지)"
echo "   6. 위 안내에 따라 L4 모델 다운로드 후 .env 경로 확인"
echo "========================================="
