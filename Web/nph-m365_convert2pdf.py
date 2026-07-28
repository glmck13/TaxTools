#!/usr/bin/env python3

import os
import subprocess
import sys
import traceback
import uuid
import urllib.parse
import extract_msg  # Required: pip install extract-msg

def run_command(command_list):
    """Executes system commands and returns output."""
    log.append(f"EXECUTE: {' '.join(command_list)}")
    result = subprocess.run(command_list, capture_output=True, text=True, shell=False)
    if result.returncode != 0:
        raise Exception(f"Command Error: {result.stderr}")
    return result.stdout

def run_m365(command_list):
    """Specific wrapper for M365 CLI."""
    return run_command(["m365"] + command_list + ["--output", "text"])

log = ["--- PDF Conversion Processing Started ---"]

try:
    # 2. PARAMETER PARSING
    raw_qs = os.environ.get('QUERY_STRING', '')
    parsed_qs = urllib.parse.parse_qs(raw_qs)
    
    def get_val(key):
        val_list = parsed_qs.get(key, [None])
        val = val_list[0]
        return urllib.parse.unquote_plus(val).strip() if val else None

    site_url = get_val("siteUrl")
    file_url = get_val("fileUrl")   
    folder_url = get_val("folderUrl")

    if not all([site_url, file_url, folder_url]):
        raise Exception("Missing parameters. Check Power Automate URL construction.")

    # 3. WORKSPACE SETUP
    run_id = str(uuid.uuid4())
    work_dir = os.path.join("/tmp", f"pdf_work_{run_id}")
    os.makedirs(work_dir, exist_ok=True)
    
    # Extract filename to preserve extension for the converters
    original_filename = os.path.basename(file_url)
    local_input_path = os.path.join(work_dir, original_filename)
    
    log.append(f"Processing File: {original_filename}")

    # 4. DOWNLOAD
    log.append("Step: Downloading source file...")
    run_m365([
        "spo", "file", "get", 
        "--webUrl", site_url, 
        "--url", file_url,      
        "--asFile",           
        "--path", local_input_path 
    ])

    # 5. CONVERSION LOGIC
    ext = os.path.splitext(original_filename)[1].lower()
    pdf_filename = os.path.splitext(original_filename)[0] + ".pdf"
    local_pdf_path = os.path.join(work_dir, pdf_filename)

    # --- MSG Handling Logic ---
    if ext == '.msg':
        log.append("Step: Processing Outlook .msg file...")
        msg_obj = extract_msg.Message(local_input_path)
        
        # Extract Headers
        m_from = msg_obj.sender or "Unknown"
        m_to = msg_obj.to or "Unknown"
        m_date = msg_obj.date or "Unknown"
        m_subject = msg_obj.subject or "(No Subject)"
        
        header_html = f"""
        <div style="font-family: Arial, sans-serif; margin-bottom: 20px; border-bottom: 2px solid #333; padding-bottom: 10px;">
            <p style="margin: 2px 0;"><b>From:</b> {m_from}</p>
            <p style="margin: 2px 0;"><b>Sent:</b> {m_date}</p>
            <p style="margin: 2px 0;"><b>To:</b> {m_to}</p>
            <p style="margin: 2px 0;"><b>Subject:</b> {m_subject}</p>
        </div>
        """
        
        # Extract Body (Prefer HTML, fallback to Text)
        if msg_obj.htmlBody:
            body_content = msg_obj.htmlBody.decode('utf-8', errors='ignore')
        else:
            # Preserve line breaks for plain text emails
            body_content = f"<div style='white-space: pre-wrap; font-family: monospace;'>{msg_obj.body}</div>"
            
        full_content = header_html + body_content
        
        # Redirect local_input_path to the new HTML file for LibreOffice
        local_input_path = os.path.join(work_dir, os.path.splitext(original_filename)[0] + ".html")
        
        with open(local_input_path, "w", encoding="utf-8") as f:
            f.write(full_content)
        
        msg_obj.close()
        ext = '.html' # Pass control to the Office conversion logic
    # --- End MSG Handling ---

    office_extensions = ['.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.html', '.htm', '.csv']
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff']

    if ext in office_extensions:
        log.append(f"Converting {ext} via LibreOffice...")
        # LibreOffice outputs to the same dir with the same name + .pdf
        run_command([
            "libreoffice", "--headless", "--convert-to", "pdf", 
            "--outdir", work_dir, local_input_path
        ])
    elif ext in image_extensions:
        log.append(f"Converting image {ext} via img2pdf...")
        run_command([
            "img2pdf", "--first-frame-only", local_input_path, "--output", local_pdf_path
        ])
    else:
        raise Exception(f"Unsupported file extension: {ext}")

    # --- New: PDF Compression via Ghostscript ---
    if os.path.exists(local_pdf_path):
        log.append("Step: Compressing PDF via Ghostscript...")
        compressed_pdf_path = local_pdf_path.replace(".pdf", "_compressed.pdf")
        
        # -dPDFSETTINGS options: /screen (72dpi), /ebook (150dpi), /printer (300dpi)
        gs_command = [
            "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.4",
            "-dPDFSETTINGS=/ebook", "-dNOPAUSE", "-dQUIET", "-dBATCH",
            f"-sOutputFile={compressed_pdf_path}", local_pdf_path
        ]
        
        try:
            run_command(gs_command)
            # Replace the original PDF with the compressed version for the upload step
            os.replace(compressed_pdf_path, local_pdf_path)
            log.append(f"Compression complete. Original: {os.path.getsize(local_pdf_path)} bytes")
        except Exception as e:
            log.append(f"Compression failed, proceeding with original: {str(e)}")

    # 6. UPLOAD PDF BACK
    if os.path.exists(local_pdf_path):
        log.append(f"Step: Uploading {pdf_filename}...")
        run_m365([
            "spo", "file", "add", 
            "--webUrl", site_url, 
            "--folder", folder_url, 
            "--path", local_pdf_path
        ])
        log.append("Upload successful.")
    else:
        raise Exception("PDF file was not generated.")

    # 7. CLEANUP
    for root, dirs, files in os.walk(work_dir, topdown=False):
        for name in files: os.remove(os.path.join(root, name))
        for name in dirs: os.rmdir(os.path.join(root, name))
    os.rmdir(work_dir)
    
    log.append("--- Process Completed Successfully ---")

except Exception:
    log.append("--- CRITICAL FAILURE ---")
    log.append(traceback.format_exc())

log = "\n".join(log)

# 1. HEADERS
byte_length = len(log.encode('utf-8'))
print("HTTP/1.1 200 OK", end="\r\n")
print("Content-Type: text/plain", end="\r\n")
print(f"Content-Length: {byte_length}", end="\r\n")
print("Content-Disposition: attachment; filename=\"conversion_log.txt\"", end="\r\n")
print("", end="\r\n")

print(log, end='')
