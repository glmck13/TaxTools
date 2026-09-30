#!/usr/bin/env python3
import html
import os
import sys
import urllib.parse
import requests


def get_env_var(var_name):
    """Retrieve required environment variable or exit with HTML error."""
    val = os.environ.get(var_name)
    if not val:
        print("Content-Type: text/html\n")
        print("<h2>Configuration Error</h2>")
        print(f"<p>Environment variable <code>{var_name}</code> is not set in Apache.</p>")
        sys.exit(0)
    return val.rstrip('/')


def parse_query_params():
    """Parse GET query string natively without relying on the deprecated cgi module."""
    query_string = os.environ.get("QUERY_STRING", "")
    params = urllib.parse.parse_qs(query_string)
    return {k: v[0] for k, v in params.items() if v}


def handle_pdf_download(api_base, access_token, agreement_id, doc_type="combined"):
    """
    Fetch PDF from Adobe API and stream directly to the browser for inline rendering.
    Supports both combined signed agreement PDF and formal Audit Trail PDF.
    """
    endpoint = "auditTrail" if doc_type == "audit" else "combinedDocument"
    filename_prefix = "audit_trail" if doc_type == "audit" else "agreement"
    
    url = f"{api_base}/agreements/{agreement_id}/{endpoint}"
    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=30)
        if resp.status_code == 200:
            sys.stdout.buffer.write(b"Content-Type: application/pdf\r\n")
            sys.stdout.buffer.write(
                f'Content-Disposition: inline; filename="{filename_prefix}_{agreement_id}.pdf"\r\n\r\n'.encode('utf-8')
            )
            
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
            sys.exit(0)
        else:
            print("Content-Type: text/html\n")
            print(f"<h3>Download Error</h3><p>Adobe API returned status code {resp.status_code}</p>")
            sys.exit(0)
    except Exception as e:
        print("Content-Type: text/html\n")
        print(f"<h3>Download Exception</h3><p>{html.escape(str(e))}</p>")
        sys.exit(0)


def fetch_agreements(api_base, access_token):
    """Fetch agreement list from Adobe Acrobat Sign API."""
    url = f"{api_base}/agreements"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def render_html_page(agreements, error_message=None):
    """Render HTML report with inline CSS and Vanilla JS for sorting, filtering, and pagination."""
    
    table_rows = []
    if agreements:
        for item in agreements:
            raw_id = item.get("id") or ""
            agr_id = html.escape(raw_id)
            name = html.escape(item.get("name") or "Untitled")
            status = html.escape(item.get("status") or "UNKNOWN")
            
            # Parse displayDate
            raw_date = item.get("displayDate") or ""
            display_date = html.escape(raw_date.split("T")[0] if "T" in raw_date else raw_date)
            
            # Parse Signers safely
            signers = []
            participant_sets = item.get("displayParticipantSetInfos") or []
            for pset in participant_sets:
                for member in pset.get("displayUserSetMemberInfos") or []:
                    full_name = html.escape(member.get("fullName") or "N/A")
                    email = html.escape(member.get("email") or "N/A")
                    signers.append(f"{full_name} &lt;{email}&gt;")
            
            signer_str = ", ".join(signers) if signers else "N/A"
            
            # Construct Download URLs for combined PDF and Audit Trail
            script_name = os.environ.get("SCRIPT_NAME", "")
            quoted_id = urllib.parse.quote(agr_id)
            download_pdf_url = f"{script_name}?download_id={quoted_id}&type=combined"
            download_audit_url = f"{script_name}?download_id={quoted_id}&type=audit"
            
            # Determine if document can be downloaded
            is_downloadable = status.upper() in ["SIGNED", "COMPLETED", "APPROVED", "DELIVERED", "ACCEPTED"]
            
            if is_downloadable:
                action_cell = (
                    f'<div class="action-buttons">'
                    f'<a href="{download_pdf_url}" target="_blank" class="btn-download">PDF</a>'
                    f'<a href="{download_audit_url}" target="_blank" class="btn-download btn-audit">Audit</a>'
                    f'</div>'
                )
            else:
                action_cell = '<span style="color: #8c9196; font-size: 0.8rem;">In Progress</span>'
            
            row_html = f"""
            <tr data-filtered="true">
                <td title="Adobe ID: {agr_id}"><strong>{name}</strong></td>
                <td><span class="badge badge-{status.lower()}">{status}</span></td>
                <td class="col-date">{display_date}</td>
                <td>{signer_str}</td>
                <td style="text-align: center;">{action_cell}</td>
            </tr>
            """
            table_rows.append(row_html)
            
    table_body_content = "".join(table_rows) if table_rows else '<tr id="noDataRow"><td colspan="5" style="text-align:center;">No agreements found.</td></tr>'
    error_banner = f'<div class="error-banner">{html.escape(error_message)}</div>' if error_message else ""

    html_document = f"""Content-Type: text/html; charset=utf-8

<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Adobe Sign Agreements Report</title>
    <style>
        :root {{
            --bg-color: #f8f9fa;
            --card-bg: #ffffff;
            --text-color: #212529;
            --border-color: #dee2e6;
            --primary-color: #0265dc;
            --primary-hover: #014bb4;
            --audit-color: #5c6ac4;
            --audit-hover: #4954a4;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 30px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: var(--card-bg);
            padding: 25px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-bottom: 2px solid var(--border-color);
            padding-bottom: 15px;
        }}
        h1 {{ margin: 0; font-size: 1.5rem; }}
        .search-box {{
            padding: 8px 14px;
            width: 280px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 0.9rem;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }}
        th, td {{
            text-align: left;
            padding: 12px 14px;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.9rem;
        }}
        th {{
            background-color: #f1f3f5;
            cursor: pointer;
            user-select: none;
        }}
        th:hover {{ background-color: #e9ecef; }}
        th::after {{
            content: " ↕";
            font-size: 0.75rem;
            color: #888;
        }}
        tr:hover {{ background-color: #f8f9fa; }}
        code {{ font-family: monospace; background: #e9ecef; padding: 2px 5px; border-radius: 3px; }}
        .badge {{
            padding: 4px 8px;
            border-radius: 12px;
            font-size: 0.75rem;
            font-weight: bold;
            text-transform: uppercase;
            white-space: nowrap;
        }}
        .badge-signed, .badge-completed {{ background: #d4edda; color: #155724; }}
        .badge-out_for_signature {{ background: #fff3cd; color: #856404; }}
        .badge-waiting_for_my_signature {{ background: #fce8e6; color: #c5221f; }}
        .badge-draft {{ background: #e2e3e5; color: #383d41; }}
        
        .col-date {{
            white-space: nowrap;
            min-width: 110px;
        }}
        
        .action-buttons {{
            display: flex;
            gap: 6px;
            justify-content: center;
            align-items: center;
        }}
        .btn-download {{
            display: inline-block;
            padding: 5px 10px;
            background-color: var(--primary-color);
            color: #fff;
            text-decoration: none;
            border-radius: 4px;
            font-size: 0.75rem;
            font-weight: 600;
            white-space: nowrap;
            line-height: 1.2;
        }}
        .btn-download:hover {{ background-color: var(--primary-hover); }}
        .btn-audit {{
            background-color: var(--audit-color);
        }}
        .btn-audit:hover {{
            background-color: var(--audit-hover);
        }}
        .error-banner {{
            background-color: #f8d7da;
            color: #721c24;
            padding: 12px;
            border-radius: 4px;
            margin-bottom: 20px;
            border: 1px solid #f5c6cb;
        }}
        
        /* Pagination Controls CSS */
        .pagination-container {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid var(--border-color);
        }}
        .pagination-select-group {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 0.85rem;
            color: #555;
        }}
        .pagination-select {{
            padding: 5px 8px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 0.85rem;
            background-color: #fff;
        }}
        .pagination-buttons {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .btn-page {{
            padding: 6px 14px;
            background-color: #fff;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 0.85rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .btn-page:hover:not(:disabled) {{
            background-color: #e9ecef;
            border-color: #ced4da;
        }}
        .btn-page:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
        }}
        .page-info {{
            font-size: 0.85rem;
            color: #555;
            font-weight: 500;
        }}
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>Adobe Sign Agreements</h1>
        <input type="text" id="searchInput" class="search-box" placeholder="Filter agreements..." onkeyup="filterTable()">
    </header>

    {error_banner}

    <table id="agreementsTable">
        <thead>
            <tr>
                <th onclick="sortTable(0)">Document Name</th>
                <th onclick="sortTable(1)">Status</th>
                <th onclick="sortTable(2)" class="col-date">Date</th>
                <th onclick="sortTable(3)">Signers</th>
                <th style="text-align: center; cursor: default;">Actions</th>
            </tr>
        </thead>
        <tbody>
            {table_body_content}
        </tbody>
    </table>

    <div class="pagination-container">
        <div class="pagination-select-group">
            <label for="pageSizeSelect">Items per page:</label>
            <select id="pageSizeSelect" class="pagination-select" onchange="changePageSize()">
                <option value="10" selected>10</option>
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
            </select>
        </div>
        <div class="pagination-buttons">
            <button id="prevBtn" class="btn-page" onclick="changePage(-1)">&laquo; Previous</button>
            <span id="pageInfo" class="page-info">Page 1 of 1</span>
            <button id="nextBtn" class="btn-page" onclick="changePage(1)">Next &raquo;</button>
        </div>
    </div>
</div>

<script>
let currentPage = 1;
let pageSize = 10;

function getVisibleRows() {{
    const table = document.getElementById("agreementsTable");
    return Array.from(table.querySelectorAll("tbody tr:not(#noDataRow)"))
                .filter(tr => tr.getAttribute("data-filtered") === "true");
}}

function updatePagination() {{
    const rows = getVisibleRows();
    const totalPages = Math.ceil(rows.length / pageSize) || 1;
    
    if (currentPage > totalPages) currentPage = totalPages;
    if (currentPage < 1) currentPage = 1;

    const start = (currentPage - 1) * pageSize;
    const end = start + pageSize;

    rows.forEach((tr, index) => {{
        tr.style.display = (index >= start && index < end) ? "" : "none";
    }});

    document.getElementById("pageInfo").textContent = `Page ${{currentPage}} of ${{totalPages}} (${{rows.length}} total)`;
    document.getElementById("prevBtn").disabled = currentPage === 1;
    document.getElementById("nextBtn").disabled = currentPage === totalPages || totalPages === 0;
}}

function changePage(direction) {{
    currentPage += direction;
    updatePagination();
}}

function changePageSize() {{
    const select = document.getElementById("pageSizeSelect");
    pageSize = parseInt(select.value, 10);
    currentPage = 1;
    updatePagination();
}}

function filterTable() {{
    const input = document.getElementById("searchInput");
    const filter = input.value.toLowerCase();
    const table = document.getElementById("agreementsTable");
    const trs = table.querySelectorAll("tbody tr:not(#noDataRow)");

    trs.forEach(tr => {{
        const text = tr.textContent.toLowerCase();
        const matches = text.includes(filter);
        tr.setAttribute("data-filtered", matches ? "true" : "false");
        if (!matches) tr.style.display = "none";
    }});

    currentPage = 1;
    updatePagination();
}}

let sortDirections = {{}};
function sortTable(columnIndex) {{
    const table = document.getElementById("agreementsTable");
    const tbody = table.querySelector("tbody");
    const rows = Array.from(tbody.querySelectorAll("tr:not(#noDataRow)"));

    if (rows.length === 0) return;

    sortDirections[columnIndex] = !sortDirections[columnIndex];
    const ascending = sortDirections[columnIndex];

    rows.sort((rowA, rowB) => {{
        const cellA = rowA.children[columnIndex].textContent.trim().toLowerCase();
        const cellB = rowB.children[columnIndex].textContent.trim().toLowerCase();

        if (cellA < cellB) return ascending ? -1 : 1;
        if (cellA > cellB) return ascending ? 1 : -1;
        return 0;
    }});

    rows.forEach(row => tbody.appendChild(row));
    updatePagination();
}}

// Run table initialization on load
filterTable();
</script>

</body>
</html>
"""
    print(html_document)


def main():
    api_base = get_env_var("ADOBE_APIBASE")
    access_token = get_env_var("ADOBE_ACCESS_TOKEN")
    
    params = parse_query_params()
    download_id = params.get("download_id")
    doc_type = params.get("type", "combined")
    
    # Route for streaming inline PDF files (PDF or Audit Trail)
    if download_id:
        handle_pdf_download(api_base, access_token, download_id, doc_type)
        return

    # Route for displaying the main HTML table
    try:
        data = fetch_agreements(api_base, access_token)
        agreements = data.get("userAgreementList", [])
        render_html_page(agreements)
    except requests.exceptions.RequestException as e:
        render_html_page([], error_message=f"API Request Failed: {str(e)}")


if __name__ == "__main__":
    main()