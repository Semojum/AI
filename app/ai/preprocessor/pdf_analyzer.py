import fitz

MIN_TEXT_LENGTH = 10


def analyze_pdf(pdf_path: str, page_no: int) -> str:
    """
    page_no: 1-indexed
    Returns 'TEXT_NATIVE' or 'OCR'
    """
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_no - 1]
        has_text = len(page.get_text().strip()) >= MIN_TEXT_LENGTH
    finally:
        doc.close()
    return "TEXT_NATIVE" if has_text else "OCR"
