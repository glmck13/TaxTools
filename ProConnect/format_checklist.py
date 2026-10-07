#!/usr/bin/env python3

import argparse
import html
import json
import re
import sys


def clean_item_text(text):
    """Strips boilerplate instruction prefixes from document requests."""
    if not text:
        return ""
    pattern = r'^(?:Please\s+)?(?:upload|provide|submit|share)(?:\s+all|\s+your|\s+us)?\s+'
    cleaned = re.sub(pattern, '', str(text), flags=re.IGNORECASE)
    return cleaned.strip()


def generate_html_checklist(json_input: str, output_html_path: str):
    try:
        if json_input == "-":
            raw_input = sys.stdin.read()
            if not raw_input.strip():
                sys.stderr.write("No JSON received on stdin. Skipping HTML generation.\n")
                sys.exit(0)
            data = json.loads(raw_input)
        else:
            with open(json_input, "r", encoding="utf-8") as f:
                data = json.load(f)
    except Exception as e:
        input_name = "stdin" if json_input == "-" else f"file '{json_input}'"
        sys.stderr.write(f"Error loading JSON from {input_name}: {e}\n")
        sys.exit(1)

    if not isinstance(data, dict):
        sys.stderr.write("Error: Expected a JSON object at root level.\n")
        sys.exit(1)

    client_name = html.escape(str(data.get("client_name") or "Unknown Client"))
    return_name = html.escape(str(data.get("return_name") or "N/A"))
    client_id = html.escape(str(data.get("client_id") or "N/A"))

    # Flexible handling for both wrapped custom payloads and raw API payloads
    checklist_obj = data.get("checklist") if "checklist" in data else data
    source_docs = checklist_obj.get("sourceDocuments") if isinstance(checklist_obj, dict) else []
    source_docs = source_docs or []

    # Group source documents by type
    categories = {}
    for doc in source_docs:
        if isinstance(doc, dict):
            doc_type = str(doc.get("sourceDocumentType") or "Other").upper()
            categories.setdefault(doc_type, []).append(doc)

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Document Checklist - {client_name}</title>
    <style>
        :root {{
            --primary: #1e3a8a;
            --border: #cbd5e1;
            --bg-alt: #f8fafc;
            --text: #0f172a;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            color: var(--text);
            margin: 0;
            padding: 20px;
            background-color: #f1f5f9;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: #ffffff;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        h1 {{
            color: var(--primary);
            margin-top: 0;
            border-bottom: 2px solid var(--primary);
            padding-bottom: 10px;
            font-size: 24px;
        }}
        h2 {{
            color: #334155;
            font-size: 18px;
            margin-top: 25px;
            margin-bottom: 10px;
            background: #e2e8f0;
            padding: 8px 12px;
            border-radius: 4px;
        }}
        .instruction-box {{
            background-color: #eff6ff;
            border-left: 4px solid #3b82f6;
            padding: 12px 16px;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .meta-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        .meta-table td {{
            padding: 6px 12px;
            border: 1px solid var(--border);
        }}
        .meta-label {{
            font-weight: bold;
            background-color: var(--bg-alt);
            width: 25%;
        }}
        table.checklist-table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
            font-size: 14px;
        }}
        table.checklist-table th, table.checklist-table td {{
            border: 1px solid var(--border);
            padding: 10px 12px;
            text-align: left;
        }}
        table.checklist-table th {{
            background-color: var(--bg-alt);
            font-weight: 600;
        }}
        .col-check {{ width: 8%; text-align: center; }}
        .col-num {{ width: 8%; text-align: center; }}
        .col-desc {{ width: 84%; }}
        
        input[type="checkbox"] {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}

        @media print {{
            body {{ background: #fff; padding: 0; }}
            .container {{ box-shadow: none; padding: 0; max-width: 100%; }}
            input[type="checkbox"] {{ border: 1px solid #cbd5e1 !important; }}
        }}
    </style>
</head>
<body>

<div class="container">
    <h1>Client Tax Document Checklist</h1>
    
    <table class="meta-table">
        <tr>
            <td class="meta-label">Client Name</td>
            <td>{client_name}</td>
            <td class="meta-label">Client ID</td>
            <td>{client_id}</td>
        </tr>
        <tr>
            <td class="meta-label">Return Name</td>
            <td colspan="3">{return_name}</td>
        </tr>
    </table>

    <div class="instruction-box">
        <strong>Instructions:</strong> Please gather the requested tax documents listed below. Check off each item as you collect it and submit all supporting files or copies to your tax preparer.
    </div>
"""

    if not categories:
        html_content += "<p>No required source documents were requested for this client.</p>"
    else:
        item_counter = 1
        for category, docs in categories.items():
            category_title = html.escape(category)
            html_content += f"""
            <h2>Category: {category_title}</h2>
            <table class="checklist-table">
                <thead>
                    <tr>
                        <th class="col-check">Status</th>
                        <th class="col-num">#</th>
                        <th class="col-desc">Document Requested</th>
                    </tr>
                </thead>
                <tbody>
            """
            for doc in docs:
                raw_text = doc.get("text", "")
                display_text = html.escape(clean_item_text(raw_text))
                html_content += f"""
                    <tr>
                        <td class="col-check"><input type="checkbox"></td>
                        <td class="col-num">{item_counter}</td>
                        <td class="col-desc">{display_text}</td>
                    </tr>
                """
                item_counter += 1

            html_content += """
                </tbody>
            </table>
            """

    html_content += """
</div>
</body>
</html>
"""

    if output_html_path == "-":
        sys.stdout.buffer.write(html_content.encode("utf-8"))
        sys.stdout.buffer.flush()
    else:
        with open(output_html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        sys.stderr.write(f"Successfully generated HTML checklist: '{output_html_path}'\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert raw tax document checklist JSON into an interactive HTML checklist."
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default="-",
        help="Path to input checklist JSON file, or '-' / omit for stdin (default: -)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="doc_checklist.html",
        help="Path for output HTML checklist file (or '-' for stdout, default: doc_checklist.html)",
    )
    args = parser.parse_args()

    generate_html_checklist(args.json_path, args.output)