#!/usr/bin/env bash
# proto 컴파일 스크립트 — 프로젝트 루트에서 실행: bash protos/build.sh
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$ROOT/protos/generated"

python -m grpc_tools.protoc \
    -I "$ROOT/protos" \
    --python_out="$ROOT/protos/generated" \
    --grpc_python_out="$ROOT/protos/generated" \
    "$ROOT/protos/braille_service.proto"

# grpc_tools 생성 파일의 import 경로 수정
# (생성된 파일이 'import braille_service_pb2'로 절대 임포트하므로 패키지 경로로 교체)
GRPC_FILE="$ROOT/protos/generated/braille_service_pb2_grpc.py"
if grep -q "^import braille_service_pb2" "$GRPC_FILE" 2>/dev/null; then
    sed -i 's/^import braille_service_pb2/from protos.generated import braille_service_pb2/' "$GRPC_FILE"
fi

touch "$ROOT/protos/generated/__init__.py"

echo "proto 빌드 완료:"
ls -lh "$ROOT/protos/generated/"
