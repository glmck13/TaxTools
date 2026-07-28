#!/usr/bin/env python3

import json
import subprocess
import os
import sys
import tempfile
import shutil
import re
import traceback
import concurrent.futures
import requests
from urllib.parse import parse_qs
from pypdf import PdfReader, PdfWriter

# Configuration
SPO_URL = "https://tarrantadvisors.sharepoint.com/sites/Company"
BASE_FOLDER = "/Shared Documents"
SUB_FOLDER = "/2025" 

# --- Native CGI Replacements for Python 3.13+ ---
class MiniFieldStorage:
    """A lightweight, native replacement for cgi.FieldStorage"""
    def __init__(self):
        self.data = {}
        method = os.environ.get("REQUEST_METHOD", "GET").upper()
        
        if method == "POST":
            try:
                content_length = int(os.environ.get("CONTENT_LENGTH", 0))
                query_string = sys.stdin.read(content_length)
            except ValueError:
                query_string = ""
        else:
            query_string = os.environ.get("QUERY_STRING", "")

        # parse_qs returns a dictionary where values are lists: {'key': ['value1', 'value2']}
        self.data = parse_qs(query_string, keep_blank_values=True)

    def getvalue(self, key, default=None):
        """Mimics the behavior of cgi.FieldStorage().getvalue()"""
        if key in self.data:
            return self.data[key][0] 
        return default

def enable_cgitb():
    """A native replacement for cgitb.enable() to print traceback to the browser"""
    def handle_exception(exc_type, exc_value, exc_traceback):
        print("Content-Type: text/html\n")
        print("<html><head><title>Error</title></head><body>")
        print("<h2 style='color: #d83b01;'>Traceback (Python 3.13 Native)</h2><pre style='background: #f4f4f4; padding: 15px;'>")
        traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stdout)
        print("</pre></body></html>")
    sys.excepthook = handle_exception

# Enable the custom traceback handler
enable_cgitb()
# ------------------------------------------------

def run_cli(command):
    """Helper to run M365 CLI commands with error detection."""
    full_cmd = ["m365"] + command + ["--output", "json"]
    result = subprocess.run(full_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        if isinstance(data, dict) and "error" in data:
            return None
        return data
    except:
        return None

def parse_range(range_str, max_val):
    """Parses a string like '1,3,5-7' and returns a list of integers."""
    if not range_str or not range_str.strip():
        return list(range(1, max_val + 1))
    items = []
    parts = [p.strip() for p in range_str.split(',') if p.strip()]
    try:
        for part in parts:
            if '-' in part:
                start, end = map(int, part.split('-'))
                if start < 1 or end > max_val or start > end: return None
                items.extend(range(start, end + 1))
            else:
                val = int(part)
                if val < 1 or val > max_val: return None
                items.append(val)
        return items
    except ValueError:
        return None

def get_page_count_worker_fast(args):
    """Downloads via REST API and uses pypdf to check pages and encryption."""
    pdf, tmp_dir, i, access_token = args
    file_url = pdf["ServerRelativeUrl"]
    local_pdf = os.path.join(tmp_dir, f"check_{i}.pdf")
    
    try:
        download_url = f"{SPO_URL}/_api/web/GetFileByServerRelativeUrl('{file_url}')/$value"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        with requests.get(download_url, headers=headers, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(local_pdf, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        reader = PdfReader(local_pdf)
        pages = len(reader.pages)
        is_encrypted = reader.is_encrypted
        
        return {**pdf, "pages": pages, "index": i, "encrypted": is_encrypted}
    except Exception as e:
        return {**pdf, "pages": 0, "index": i, "error": str(e), "encrypted": False}
    finally:
        if os.path.exists(local_pdf):
            os.remove(local_pdf)

def download_worker(args):
    """Simple worker to download files in parallel for the final merge."""
    i, file_url, p_range, max_p, tmp_dir, access_token, name = args
    local_src = os.path.join(tmp_dir, f"src_{i}.pdf")
    
    try:
        download_url = f"{SPO_URL}/_api/web/GetFileByServerRelativeUrl('{file_url}')/$value"
        headers = {"Authorization": f"Bearer {access_token}"}
        
        with requests.get(download_url, headers=headers, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(local_src, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        
        return {"index": i, "path": local_src, "range": p_range, "max_p": max_p, "name": name}
    except Exception as e:
        return {"index": i, "error": str(e)}

def print_html_head(title):
    print("Content-Type: text/html\n")
    print(f"<html><head><title>{title}</title>")
    print("""
    <style>
        body { font-family: 'Segoe UI', sans-serif; width: 800px; margin: 20px; color: #333; font-size: 14px; }
        .item { display: flex; align-items: center; padding: 4px 10px; border-bottom: 1px solid #eee; gap: 15px; }
        .file-name { flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 115%; }
        .page-badge { color: #666; font-size: 0.85em; min-width: 60px; font-size: 115%; }
        input[type="text"] { border: 1px solid #ccc; border-radius: 3px; padding: 3px 6px; }
        .extract-box { width: 100px; }
        .btn { background: #0078d4; color: white; border: none; padding: 8px 20px; border-radius: 4px; cursor: pointer; font-weight: bold; text-decoration: none; display: inline-block; }
        .btn:hover { background: #005a9e; }
        .controls { background: #f3f2f1; padding: 15px; border-radius: 4px; margin-bottom: 15px; border: 1px solid #e1dfdd; }
        .manifest { width: 100%; border-collapse: collapse; margin-top: 20px; }
        .manifest th, .manifest td { text-align: left; padding: 10px; border-bottom: 1px solid #ddd; }
        .manifest th { background: #f8f8f8; }
        #loading-overlay { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(255, 255, 255, 0.9); z-index: 9999; text-align: center; padding-top: 10%; }
        .spinner { border: 6px solid #f3f3f3; border-top: 6px solid #0078d4; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; display: inline-block; vertical-align: middle; margin-right: 10px; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
    <script>
        function showLoading(msg) {
            document.getElementById('loading-overlay').style.display = 'block';
            if(msg) document.getElementById('loading-text').innerText = msg;
        }
    </script>
    """)
    print(f"</head><body><h1>{title}</h1>")
    print('<div id="loading-overlay"><div class="spinner"></div><h2 id="loading-text" style="display:inline-block;">Processing...</h2></div>')

def print_error(msg):
    print_html_head("Error")
    print(f"<div style='background:#fde7e9; padding:15px; border-left:5px solid #d83b01;'><strong>Error:</strong> {msg}</div>")
    print('<br><a href="javascript:history.back()">&larr; Go Back</a>')
    print("</body></html>")

def handle_step_1():
    print_html_head("Select Client Folder")
    raw_folders = run_cli(["spo", "folder", "list", "--webUrl", SPO_URL, "--parentFolderUrl", BASE_FOLDER])
    if raw_folders:
        folders = sorted(raw_folders, key=lambda x: x['Name'].lower())
        print('<form method="POST" onsubmit="showLoading(\'Loading subfolders...\')">')
        print('<select name="selected_folder" style="padding:5px; width:400px;">')
        for folder in folders:
            print(f'<option value="{folder["ServerRelativeUrl"]}">{folder["Name"]}</option>')
        print('</select>')
        print('<input type="hidden" name="step" value="2">')
        print('<input type="submit" value="Analyze Client" class="btn" style="margin-left:10px;">')
        print('</form>')
    else:
        print("<p>No folders found.</p>")
    print("</body></html>")

def handle_step_2(folder_url):
    target_path = f"{folder_url.rstrip('/')}/{SUB_FOLDER.lstrip('/')}"
    folder_name = os.path.basename(folder_url.rstrip('/'))
    print_html_head(f"Select Subfolder: {folder_name}{SUB_FOLDER}")
    subfolders = run_cli(["spo", "folder", "list", "--webUrl", SPO_URL, "--parentFolderUrl", target_path])
    if subfolders:
        folders = sorted(subfolders, key=lambda x: x['Name'].lower())
        print('<form method="POST" onsubmit="showLoading(\'Analyzing files...\')">')
        print('<select name="target_subfolder" style="padding:5px; width:400px;">')
        for folder in folders:
            print(f'<option value="{folder["ServerRelativeUrl"]}">{folder["Name"]}</option>')
        print('</select>')
        print(f'<input type="hidden" name="folder_name" value="{folder_name}">')
        print(f'<input type="hidden" name="selected_folder" value="{folder_url}">')
        print('<input type="hidden" name="step" value="2.5">')
        print('<input type="submit" value="Select Folder" class="btn" style="margin-left:10px;">')
        print('</form>')
    else:
        print_error(f"No subfolders found in {target_path}")
    print("</body></html>")

def handle_step_2_5(target_path, folder_name, folder_url):
    sub_display = os.path.basename(target_path.rstrip('/'))
    print_html_head(f"Configure Merge: {folder_name} &raquo; {sub_display}")
    
    files = run_cli(["spo", "file", "list", "--webUrl", SPO_URL, "--folderUrl", target_path, "--recursive"])
    if files is None: return print_error(f"Folder not found: {target_path}")

    source_files = [f for f in files if f['Name'].lower().endswith('.pdf')]
    source_files = sorted(source_files, key=lambda x: x['ServerRelativeUrl'])
    
    if source_files:
        token_cmd = ["m365", "util", "accesstoken", "get", "--resource", "https://tarrantadvisors.sharepoint.com", "--output", "text"]
        token_res = subprocess.run(token_cmd, capture_output=True, text=True)
        access_token = token_res.stdout.strip()

        print('<form method="POST" onsubmit="showLoading(\'Verifying ranges...\')">')
        print('<div class="controls">')
        print('  <div style="display: flex; justify-content: space-between; align-items: center;">')
        print('    <div>')
        print('      <label style="cursor:pointer; margin-right: 20px;">')
        print('        <input type="checkbox" name="select_all" value="yes"> <strong>Merge All (Unlocked) Files</strong>')
        print('      </label>')
        print('      Order: <input type="text" name="selections" placeholder="e.g. 1-3,5" style="width:150px;">')
        print('    </div>')
        print('    <input type="submit" value="Preview Summary &rarr;" class="btn">')
        print('  </div>')
        print('</div>')
        
        info_tmp = tempfile.mkdtemp()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                tasks = [(f, info_tmp, i, access_token) for i, f in enumerate(source_files, 1)]
                enriched_files = list(executor.map(get_page_count_worker_fast, tasks))
        finally:
            shutil.rmtree(info_tmp)
        
        for pdf in sorted(enriched_files, key=lambda x: x['index']):
            i = pdf['index']
            target_href = "/".join(SPO_URL.split("/")[:3]) + pdf["ServerRelativeUrl"]
            pages = pdf.get('pages', 0)
            is_enc = pdf.get('encrypted', False)
            
            item_style = "background-color: #fff4f4;" if is_enc else ""
            warning = " <span style='color:#d83b01; font-weight:bold;'>[ENCRYPTED - CANNOT MERGE]</span>" if is_enc else ""

            print(f'<div class="item" style="{item_style}">')
            print(f'  <span style="width:25px;">{i}.</span>')
            print(f'  <span class="file-name"><a href="{target_href}" target=_blank>{pdf["Name"]}</a>{warning}</span>')
            print(f'  <span class="page-badge">{pages} pgs</span>')
            
            if is_enc:
                print(f'  <span><input type="text" class="extract-box" value="LOCKED" disabled style="background:#ddd;"></span>')
            else:
                print(f'  <span>Extract: <input type="text" name="range_{i}" class="extract-box" placeholder="e.g. 1,3-5"></span>')
            
            print(f'  <input type="hidden" name="file_{i}" value="{pdf["ServerRelativeUrl"]}">')
            print(f'  <input type="hidden" name="max_pages_{i}" value="{pages}">')
            print(f'  <input type="hidden" name="name_{i}" value="{pdf["Name"]}">')
            print(f'  <input type="hidden" name="enc_{i}" value="{"yes" if is_enc else "no"}">')
            print(f'</div>')
        
        print(f'<input type="hidden" name="folder_name" value="{folder_name}">')
        print(f'<input type="hidden" name="selected_folder" value="{folder_url}">')
        print(f'<input type="hidden" name="target_subfolder" value="{target_path}">')
        print(f'<input type="hidden" name="total_count" value="{len(source_files)}">')
        print('<input type="hidden" name="step" value="3">')
        print('</form>')
    else:
        print("<p>No PDF files found in this subfolder.</p>")
    print("</body></html>")

def handle_step_3(form):
    is_all = form.getvalue("select_all") == "yes"
    selections = form.getvalue("selections", "").strip()
    total_files = int(form.getvalue("total_count", 0))
    folder_name = form.getvalue("folder_name", "merged_document")
    folder_url = form.getvalue("selected_folder")
    target_subfolder = form.getvalue("target_subfolder")
    
    initial_indices = []
    if is_all: initial_indices = list(range(1, total_files + 1))
    elif selections:
        initial_indices = parse_range(selections, total_files)
        if initial_indices is None: return print_error(f"Invalid selection: '{selections}'")
    else: return print_error("No files selected.")

    manifest = []
    total_new_pages = 0
    for i in initial_indices:
        if form.getvalue(f"enc_{i}") == "yes": continue 

        p_range_raw = form.getvalue(f"range_{i}", "").strip()
        max_p = int(form.getvalue(f"max_pages_{i}", 0))
        fname = form.getvalue(f"name_{i}", "Unknown")
        file_url = form.getvalue(f"file_{i}")
        parsed_pages = parse_range(p_range_raw, max_p)
        if parsed_pages is None: return print_error(f"Invalid range for {fname}")
        
        count = len(parsed_pages)
        total_new_pages += count
        manifest.append({'name': fname, 'range_text': p_range_raw or "Entire File", 'count': count, 'url': file_url, 'range_val': p_range_raw, 'idx': i, 'max_p': max_p})

    if not manifest: return print_error("No valid (unlocked) files selected for merge.")

    print_html_head("Summary & Build")
    print("<table class='manifest'><tr><th>#</th><th>File Name</th><th>Range</th><th>Pages</th></tr>")
    for i, e in enumerate(manifest, 1):
        print(f"<tr><td>{i}</td><td>{e['name']}</td><td>{e['range_text']}</td><td>{e['count']}</td></tr>")
    print(f"<tr style='font-weight:bold;'><td></td><td>Total Output Pages</td><td></td><td>{total_new_pages}</td></tr></table>")
    
    print(f'<form method="POST" style="margin-top:30px;"><div class="controls"><label><input type="checkbox" name="upload_to_spo" value="yes"> <strong>Upload directly to {SUB_FOLDER}</strong></label></div>')
    print(f'<input type="hidden" name="final_indices" value="{",".join([str(m["idx"]) for m in manifest])}">')
    print(f'<input type="hidden" name="folder_name" value="{folder_name}"><input type="hidden" name="selected_folder" value="{folder_url}"><input type="hidden" name="target_subfolder" value="{target_subfolder}">')
    for m in manifest:
        print(f'<input type="hidden" name="file_{m["idx"]}" value="{m["url"]}"><input type="hidden" name="range_{m["idx"]}" value="{m["range_val"]}"><input type="hidden" name="max_p_{m["idx"]}" value="{m["max_p"]}"><input type="hidden" name="name_{m["idx"]}" value="{m["name"]}">')
    print('<input type="hidden" name="step" value="4"><input type="submit" value="Finish & Merge" class="btn" style="padding:15px 30px; font-size:1.1em;"></form></body></html>')

def handle_step_4(form):
    """Step 4: Execute merge and bookmarking using pypdf."""
    indices_str = form.getvalue("final_indices", "")
    folder_name = form.getvalue("folder_name")
    client_root = form.getvalue("selected_folder")
    do_upload = form.getvalue("upload_to_spo") == "yes"
    upload_path = f"{client_root.rstrip('/')}/{SUB_FOLDER.lstrip('/')}"
    safe_name = "BU_Detail_" + re.sub(r'[^\w\s-]', '', folder_name).strip().replace(' ', '_')
    indices = [int(x) for x in indices_str.split(",")]

    token_cmd = ["m365", "util", "accesstoken", "get", "--resource", "https://tarrantadvisors.sharepoint.com", "--output", "text"]
    token_res = subprocess.run(token_cmd, capture_output=True, text=True)
    access_token = token_res.stdout.strip()

    tmp_dir = tempfile.mkdtemp()
    try:
        tasks = [(i, form.getvalue(f"file_{i}"), form.getvalue(f"range_{i}", ""), int(form.getvalue(f"max_p_{i}", 0)), tmp_dir, access_token, form.getvalue(f"name_{i}")) for i in indices]
        
        downloaded_data = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            downloaded_data = list(executor.map(download_worker, tasks))

        for d in downloaded_data:
            if "error" in d: return print_error(f"Download failed: {d['error']}")

        writer = PdfWriter()
        current_page_index = 0
        final_pdf_path = os.path.join(tmp_dir, f"{safe_name}.pdf")

        for item in downloaded_data:
            reader = PdfReader(item["path"])
            file_name = item["name"]
            p_range_str = item["range"]
            max_p = item["max_p"]

            # Add bookmark for the start of this file
            writer.add_outline_item(file_name, current_page_index)

            if p_range_str:
                pages_to_add = parse_range(p_range_str, max_p)
                for p_num in pages_to_add:
                    writer.add_page(reader.pages[p_num - 1])
                    current_page_index += 1
            else:
                writer.append(reader, import_outline=False)
                current_page_index += len(reader.pages)

        with open(final_pdf_path, "wb") as f:
            writer.write(f)

        if do_upload:
            target_href = "/".join(SPO_URL.split("/")[:3]) + upload_path
            run_cli(["spo", "file", "add", "--webUrl", SPO_URL, "--folder", upload_path, "--path", final_pdf_path])

            print_html_head("Merge Complete")
            print(f"<div style='background:#dff6dd; padding:20px; border-radius:4px;'>")
            print(f"<h3>Successfully Created!</h3>")
            print(f"<p>File <strong>{safe_name}.pdf</strong> (with bookmarks) has been saved to: <code>{upload_path}</code></p>")
            print(f"<a href='{target_href}' target='_blank' class='btn'>Open {SUB_FOLDER} Folder &rarr;</a>")
            print("</div></body></html>")
        else:
            print("Content-Type: application/pdf\nContent-Disposition: attachment; filename=\"%s.pdf\"\n" % safe_name)
            sys.stdout.flush()
            with open(final_pdf_path, "rb") as f: 
                shutil.copyfileobj(f, sys.stdout.buffer)
                
    except Exception as general_err:
        return print_error(f"An unexpected system error occurred: {str(general_err)}")
    finally: 
        shutil.rmtree(tmp_dir)

def main():
    form = MiniFieldStorage() # Using the new native class
    step = form.getvalue("step", "1")
    if step == "1": handle_step_1()
    elif step == "2": handle_step_2(form.getvalue("selected_folder"))
    elif step == "2.5": handle_step_2_5(form.getvalue("target_subfolder"), form.getvalue("folder_name"), form.getvalue("selected_folder"))
    elif step == "3": handle_step_3(form)
    elif step == "4": handle_step_4(form)

if __name__ == "__main__":
    main()
