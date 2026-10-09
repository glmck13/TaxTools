#!/usr/bin/env python3

import argparse
import re
import sys
import fitz  # PyMuPDF


# Regex patterns for SSN and EIN formatting
SSN_REGEX = re.compile(r"^\d{3}-\d{2}-\d{4}$")
EIN_REGEX = re.compile(r"^\d{2}-\d{7}$")


def is_schedule_page(page: fitz.Page) -> tuple[bool, str]:
    """
    Detects if a page belongs to Schedule C or Schedule E by checking form headers
    in the top region of the page.
    Returns (is_match, schedule_type).
    """
    rect = page.rect
    header_rect = fitz.Rect(0, 0, rect.width, rect.height * 0.20)
    header_text = page.get_text("text", clip=header_rect).upper()

    is_c = ("SCHEDULE C" in header_text and "PROFIT OR LOSS FROM BUSINESS" in header_text) or "SCHEDULE C (FORM 1040)" in header_text
    is_e = ("SCHEDULE E" in header_text and "SUPPLEMENTAL INCOME AND LOSS" in header_text) or "SCHEDULE E (FORM 1040)" in header_text

    if not (is_c or is_e):
        return False, ""

    sched_type = "C" if is_c else "E"
    return True, sched_type


def clean_and_redact_page(page: fitz.Page, sched_type: str):
    """
    Removes interactive form annotations and applies precise PII redactions.
    Preserves Schedule C Business Name/Address (Lines C & E) and Schedule E Property Addresses.
    """
    rect = page.rect

    # 1. Delete all form field widgets and annotations (ProConnect interactive layer fix)
    for widget in page.widgets():
        page.delete_widget(widget)
    for annot in page.annots():
        page.delete_annot(annot)

    # 2. Top Header Redaction (Taxpayer Name & SSN Header Strip)
    header_strip = fitz.Rect(0, 0, rect.width, rect.height * 0.18)
    top_anchors = ["Social security number", "Name of proprietor", "ATTACHMENT SEQUENCE NO.", "OMB No."]
    anchor_boxes = []
    
    for anchor in top_anchors:
        matches = page.search_for(anchor, clip=header_strip)
        anchor_boxes.extend(matches)

    if anchor_boxes:
        max_y = max(box.y1 for box in anchor_boxes) + 25.0
        page.add_redact_annot(fitz.Rect(0, 0, rect.width, min(max_y, rect.height * 0.20)), fill=(0, 0, 0))
    else:
        page.add_redact_annot(fitz.Rect(0, 0, rect.width, rect.height * 0.12), fill=(0, 0, 0))

    # 3. Target ONLY Schedule C Line D (Employer ID number)
    if sched_type == "C":
        for match in page.search_for("Employer ID number"):
            ein_box = fitz.Rect(match.x0, match.y0 - 2.0, rect.width, match.y1 + 14.0)
            page.add_redact_annot(ein_box, fill=(0, 0, 0))

    # 4. Label-Based Redactions for Body Items (EIN & SSN Labels)
    body_labels = ["Employer identification number", "Social security number"]
    for label in body_labels:
        for match in page.search_for(label):
            label_box = fitz.Rect(match.x0, match.y0 - 2, rect.width, match.y1 + 18)
            page.add_redact_annot(label_box, fill=(0, 0, 0))

    # 5. Regex Scanning Fallback (Purges isolated SSNs or EINs anywhere on the page)
    words = page.get_text("words")
    for w in words:
        text = w[4].strip()
        if SSN_REGEX.match(text) or EIN_REGEX.match(text):
            word_rect = fitz.Rect(w[0] - 2, w[1] - 2, w[2] + 2, w[3] + 2)
            page.add_redact_annot(word_rect, fill=(0, 0, 0))

    # 6. Execute permanent vector & text stream purging
    page.apply_redactions()


def extract_and_redact_schedules(input_pdf_path: str, output_pdf_path: str):
    """
    Extracts Schedule C and E pages and applies permanent vector stream redactions.
    """
    if input_pdf_path == "-":
        pdf_data = sys.stdin.buffer.read()
        if not pdf_data:
            sys.stderr.write("No PDF stream received on stdin.\n")
            sys.exit(0)
        src_doc = fitz.open(stream=pdf_data, filetype="pdf")
    else:
        src_doc = fitz.open(input_pdf_path)

    matched_pages = []

    # 1. Scan and detect target pages
    for idx, page in enumerate(src_doc):
        is_match, sched_type = is_schedule_page(page)
        if is_match:
            matched_pages.append({
                "src_index": idx,
                "sched_type": sched_type
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

    # 3. Apply annotations cleanup and redactions
    for idx, page in enumerate(dst_doc):
        meta = matched_pages[idx]
        clean_and_redact_page(page, sched_type=meta["sched_type"])

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
        help="Path to input PDF (or '-' for stdin)"
    )
    parser.add_argument(
        "output_pdf",
        nargs="?",
        default="sanitized_schedules.pdf",
        help="Path for output PDF (or '-' for stdout)"
    )

    args = parser.parse_args()

    extract_and_redact_schedules(
        input_pdf_path=args.input_pdf,
        output_pdf_path=args.output_pdf
    )