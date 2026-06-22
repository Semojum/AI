"""
MinerU VLM 백엔드로 PDF 단일 페이지 처리.

입력:  pdf_path, page_no (1-indexed), job_id, extraction_method
출력:  storage/jobs/{job_id}/temp/page_{no:03d}/
        mineru_raw/images/{element_id}.jpg  (이미지/표 요소)
       debug=True 시 추가:
        storage/jobs/{job_id}/temp/page_{no:03d}/merged_layout.json
반환:  merged_layout (list[dict])
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import fitz

TYPE_MAP = {
    "title":               "title",
    "text":                "text",
    "caption":             "caption",
    "interline_equation":  "formula",
    "inline_equation":     "formula",
    "equation":            "formula",
    "list":                "list_item",
    "footnote":            "footnote",
    "sidebar":             "sidebar",
    "header":              "header_footer",
    "header_footer":       "header_footer",
    "page_number":         "page_number",
    "table":               "table",
    "image":               "image",
    "chart":               "chart_graph",
    "cartoon":             "cartoon",
    "figure":              "image",
}


def _run_mineru(pdf_path: Path, out_dir: Path, page_idx: int) -> None:
    # MinerU는 별도 env에 설치(transformers 버전 충돌 회피). bare 'mineru'가 PATH에
    # 없을 수 있어 MINERU_BIN으로 실행 파일 경로를 덮어쓸 수 있게 한다(GCP는 심볼릭).
    mineru_bin = os.environ.get("MINERU_BIN", "mineru")
    cmd = [
        mineru_bin, "-p", str(pdf_path), "-o", str(out_dir),
        "-s", str(page_idx), "-e", str(page_idx),   # 도착 PDF 내 0-based 인덱스
    ]
    # 영구 mineru-api가 떠 있으면 thin client로 붙어 모델 재로드를 피한다(추출 대폭 단축).
    # 없으면 요청마다 로컬 VLM 로드(vlm-engine 폴백).
    from app.ai.parser import mineru_service
    api_url = mineru_service.get_url()
    if api_url:
        cmd += ["--api-url", api_url]
    else:
        cmd += ["-b", "vlm-engine"]
    result = subprocess.run(cmd, capture_output=False, text=True)
    if result.returncode != 0:
        print("[mineru_runner] MinerU 실행 실패", file=sys.stderr)
        sys.exit(1)


def _find_content_list(out_dir: Path) -> Path:
    candidates = list(out_dir.rglob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"content_list.json not found under {out_dir}")
    return candidates[0]


def _cleanup_mineru_output(raw_dir: Path) -> None:
    for pattern in ("*_content_list_v2.json", "*.md", "*_layout.pdf", "*_origin.pdf"):
        for f in raw_dir.rglob(pattern):
            f.unlink()


def _flatten_mineru_output(raw_dir: Path) -> None:
    """
    MinerU가 만든 {pdf_stem}/{backend}/ 중첩 구조를 raw_dir/ 바로 아래로 펼침.
    JSON → raw_dir/*.json
    이미지 → raw_dir/images/*.jpg
    빈 서브디렉토리 제거
    """
    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # JSON 파일 → raw_dir 루트
    for f in list(raw_dir.rglob("*.json")):
        if f.parent != raw_dir:
            shutil.move(str(f), str(raw_dir / f.name))

    # 이미지 파일 → raw_dir/images/
    for f in list(raw_dir.rglob("*.jpg")):
        if f.parent != images_dir:
            dst = images_dir / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))

    # 빈 서브디렉토리 제거
    for item in list(raw_dir.iterdir()):
        if item.is_dir() and item != images_dir:
            shutil.rmtree(str(item))


def _extract_text_native(fitz_page: fitz.Page, bbox: list[float]) -> str:
    w, h = fitz_page.rect.width, fitz_page.rect.height
    rect = fitz.Rect(
        bbox[0] / 1000 * w, bbox[1] / 1000 * h,
        bbox[2] / 1000 * w, bbox[3] / 1000 * h,
    )
    return fitz_page.get_text("text", clip=rect).strip()


def run(
    pdf_path: str,
    page_no: int,
    job_id: str,
    extraction_method: str,
    mineru_cache_dir: str | None = None,
    debug: bool = False,
) -> list[dict]:
    """
    pdf_path: 전체 PDF 경로
    page_no: 1-indexed
    job_id: 저장 경로 식별자
    extraction_method: 'TEXT_NATIVE' | 'OCR'
    mineru_cache_dir: 이미 mineru 결과가 있으면 재사용 (None이면 새로 실행)
    debug: True이면 merged_layout.json을 test/results/page_{no:03d}/에 저장

    반환: merged_layout (list[dict])
    """
    pdf_path = Path(pdf_path)
    base = Path("storage") / "jobs" / job_id / "temp" / f"page_{page_no:03d}"

    # proto 계약상 pdf_data는 '단일 페이지' PDF(BE가 페이지마다 1장씩 전송). page_no는
    # 원본 문서 페이지 번호(저장경로용)이므로 도착 PDF 인덱스로 그대로 쓰면 단일 페이지에서
    # 범위 초과. 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1).
    with fitz.open(str(pdf_path)) as _d:
        page_idx = max(0, min(page_no - 1, _d.page_count - 1))

    raw_dir = Path(mineru_cache_dir) if mineru_cache_dir else base / "mineru_raw"
    if not list(raw_dir.rglob("*_content_list.json")):
        raw_dir.mkdir(parents=True, exist_ok=True)
        _run_mineru(pdf_path, raw_dir, page_idx)
        _cleanup_mineru_output(raw_dir)
        _flatten_mineru_output(raw_dir)

    cl_path = _find_content_list(raw_dir)
    with open(cl_path, encoding="utf-8") as f:
        content_list = json.load(f)

    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 이미지 이름 매핑 (hash_stem → element_id): 캐시 재실행 시에도 동일 element_id 유지
    mapping_file = images_dir / "mapping.json"
    hash_to_eid: dict[str, str] = {}
    if mapping_file.exists():
        hash_to_eid = json.loads(mapping_file.read_text(encoding="utf-8"))

    # PDF 페이지 크기 (bbox 픽셀 변환용, 2x 렌더 기준)
    doc = fitz.open(str(pdf_path))
    fitz_page = doc[page_idx]
    rect = fitz_page.rect
    img_w = int(rect.width * 2)
    img_h = int(rect.height * 2)

    merged_layout = []
    order = 1

    for item in content_list:
        item_type = item.get("type", "text")
        mapped_type = TYPE_MAP.get(item_type, "text")
        if mapped_type == "image" and item.get("sub_type") == "flowchart":
            mapped_type = "chart_graph"
        bb = item.get("bbox")
        if bb is None:
            continue

        element_id = str(uuid.uuid4())
        img_path_rel = item.get("img_path")
        image_path = None

        if img_path_rel:
            # flatten 후 이미지는 raw_dir/images/{hash}.jpg 에 있음
            hash_stem = Path(img_path_rel).stem
            src = images_dir / Path(img_path_rel).name
            if src.exists():
                dst = images_dir / f"{element_id}.jpg"
                shutil.move(str(src), str(dst))
                hash_to_eid[hash_stem] = element_id
                image_path = str(dst)
            elif hash_stem in hash_to_eid:
                # 캐시 재실행: 이미 이름 변경된 파일 재사용
                element_id = hash_to_eid[hash_stem]
                existing = images_dir / f"{element_id}.jpg"
                if existing.exists():
                    image_path = str(existing)
            if item_type == "table":
                content = item.get("table_body", "")
            elif mapped_type in ("image", "chart_graph", "cartoon"):
                content = "이미지 캡셔닝 대기"
            else:
                content = item.get("content", "")
        elif mapped_type in ("image", "chart_graph", "cartoon"):
            content = "이미지 캡셔닝 대기"
        elif item_type == "list":
            content = "\n".join(item.get("list_items", []))
        else:
            content = item.get("text", "")

        # TEXT_NATIVE면 PyMuPDF 텍스트로 교체 (텍스트 타입만)
        if extraction_method == "TEXT_NATIVE" and mapped_type not in ("table", "image", "chart_graph", "cartoon"):
            content = _extract_text_native(fitz_page, bb) or content

        # page_number인데 숫자가 아닌 경우 type을 text로 정정
        if mapped_type == "page_number" and not content.strip().lstrip('-').isnumeric():
            mapped_type = "text"

        # MinerU bbox는 0~1000 정규화 좌표 → 실제 픽셀로 변환
        bb_px = [bb[0] / 1000 * img_w, bb[1] / 1000 * img_h,
                 bb[2] / 1000 * img_w, bb[3] / 1000 * img_h]

        merged_layout.append({
            "element_id": element_id,
            "reading_order": order,
            "type": mapped_type,
            "bbox": bb,
            "bbox_px": bb_px,
            # 페이지 픽셀 크기(2x 렌더 기준) — bbox_px와 같은 좌표계. BE/FE가 bbox를
            # image_width/height에 대한 비율로 매핑할 수 있게 경계파일까지 흘려보낸다.
            "page_width": img_w,
            "page_height": img_h,
            "content": content,
            "image_path": image_path,
            "heading_level": None,
            "caption_ref": None,
            "flags": [],
        })
        order += 1

    doc.close()

    # 매핑 파일 업데이트 (다음 캐시 재실행에 대비)
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(hash_to_eid, f)

    if debug:
        layout_json = [
            {k: v for k, v in el.items() if k not in ("bbox_px", "content")}
            for el in merged_layout
        ]
        with open(base / "merged_layout.json", "w", encoding="utf-8") as f:
            json.dump(layout_json, f, ensure_ascii=False, indent=2)

    print(f"[mineru_runner] page {page_no}: {len(merged_layout)}개 요소, "
          f"이미지 {sum(1 for e in merged_layout if e.get('image_path'))}개")
    return merged_layout
