#!/usr/bin/env python3

import argparse
import sys
import fitz  # PyMuPDF


def is_schedule_page(page: fitz.Page) -> tuple[bool, str, bool]:
    """
    Detects if a page belongs to Schedule C or Schedule E by checking form headers
    in the top region of the page.
    Returns (is_match, schedule_type, is_page_1).
    """
    rect = page.rect
    # Restrict header check to the top 20% of the page to avoid false matches in body text/worksheets
    header_rect = fitz.Rect(0, 0, rect.width, rect.height * 0.20)
    header_text = page.get_text("text", clip=header_rect).upper()

    is_c = ("SCHEDULE C" in header_text and "PROFIT OR LOSS FROM BUSINESS" in header_text) or "SCHEDULE C (FORM 1040)" in header_text
    is_e = ("SCHEDULE E" in header_text and "SUPPLEMENTAL INCOME AND LOSS" in header_text) or "SCHEDULE E (FORM 1040)" in header_text

    if not (is_c or is_e):
        return False, "", False

    sched_type = "C" if is_c else "E"
    
    # Check full page text to determine if page is Page 1 vs Continuation Page
    full_text_upper = page.get_text("text").upper()
    is_page_1 = "PART I" in full_text_upper or "NAME OF PROPRIETOR" in full_text_upper or "TYPE OF PROPERTY" in full_text_upper

    return True, sched_type, is_page_1


def get_redaction_height(page: fitz.Page, is_page_1: bool) -> float:
    """
    Calculates exact bottom Y-coordinate for redaction. Guarantees top PII header scrub
    without over-redacting Schedule C/E body fields.
    """
    rect = page.rect

    if not is_page_1:
        # Continuation pages (Page 2 / Part II/III/V): Cover top banner (~10% height)
        return rect.height * 0.10

    # Top header anchors located above/at the Taxpayer Name & SSN header boundary
    anchors = ["ATTACHMENT SEQUENCE NO.", "OMB NO."]
    min_depth = rect.height * 0.12  # Absolute floor for header PII
    max_depth = rect.height * 0.20  # Cap to prevent redacting Line A/B/C or Property fields

    for anchor in anchors:
        matches = page.search_for(anchor)
        if matches:
            found_y = matches[0].y1 + 4.0  # Just below header rule
            return min(max(found_y, min_depth), max_depth)

    return min_depth


def extract_and_redact_schedules(input_pdf_path: str, output_pdf_path: str):
    """
    Extracts Schedule C and E pages and applies permanent vector stream redactions.
    Supports '-' for reading stdin or writing stdout.
    """
    # Load document from stdin pipe or disk file
    if input_pdf_path == "-":
        pdf_data = sys.stdin.buffer.read()
        if not pdf_data:
            sys.stderr.write("No PDF stream received on stdin.\n")
            sys.exit(0)
        src_doc = fitz.open(stream=pdf_data, filetype="pdf")
    else:
        src_doc = fitz.open(input_pdf_path)

    matched_pages = []

    # 1. Scan and detect pages using header bounding check
    for idx, page in enumerate(src_doc):
        is_match, sched_type, is_p1 = is_schedule_page(page)
        if is_match:
            matched_pages.append({
                "src_index": idx,
                "sched_type": sched_type,
                "is_page_1": is_p1
            })

    if not matched_pages:
        sys.stderr.write(f"No Schedule C or Schedule E pages found in '{input_pdf_path}'.\n")
        src_doc.close()
        sys.exit(0)

    # 2. Slice matched pages into target document
    dst_doc = fitz.open()
    for item in matched_pages:
        dst_doc.insert_pdf(src_doc, from_page=item["src_index"], to_page=item["src_index"])

    src_doc.close()

    # 3. Apply redactions
    for idx, page in enumerate(dst_doc):
        meta = matched_pages[idx]
        rect = page.rect

        redact_bottom_y = get_redaction_height(
            page=page,
            is_page_1=meta["is_page_1"]
        )

        redact_box = fitz.Rect(0, 0, rect.width, redact_bottom_y)
        page.add_redact_annot(redact_box, fill=(0, 0, 0))

        # Permanently purge text and graphics streams
        page.apply_redactions()

    # 4. Save sanitized PDF to disk or stdout stream
    if output_pdf_path == "-":
        sys.stdout.buffer.write(dst_doc.tobytes(garbage=4, deflate=True))
        sys.stdout.buffer.flush()
    else:
        dst_doc.save(output_pdf_path, garbage=4, deflate=True)
        page_nums = [m["src_index"] + 1 for m in matched_pages]
        sys.stderr.write(f"Success! Extracted {len(matched_pages)} page(s) (Source Pages: {page_nums}) -> '{output_pdf_path}'.\n")

    dst_doc.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sanitize ProConnect/Lacerte Schedule C and Schedule E PDF exports."
    )
    parser.add_argument(
        "input_pdf", 
        nargs="?",
        default="-",
        help="Path to the input PDF file (or '-' for stdin)"
    )
    parser.add_argument(
        "output_pdf", 
        nargs="?", 
        default="sanitized_schedules.pdf", 
        help="Path for sanitized output PDF (or '-' for stdout, default: sanitized_schedules.pdf)"
    )

    args = parser.parse_args()

    extract_and_redact_schedules(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf
    )