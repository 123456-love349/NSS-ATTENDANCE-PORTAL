"""
utils/ocr_helper.py
Processes attendance sheets in various formats (CSV, Excel, PDF, Images).
Uses pandas for tabular, pypdf for digital text PDFs, and EasyOCR for images.
Matches extracted data with the master students database.
"""

import os
import re
import tempfile
import pandas as pd
from pypdf import PdfReader
import cv2
import numpy as np

_ocr_reader = None

def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        # Initialize easyocr reader (lazy-loaded to conserve memory/start time)
        _ocr_reader = easyocr.Reader(['en'], gpu=False)
    return _ocr_reader


def group_ocr_boxes_into_lines(ocr_results):
    """Group 2D bounding boxes from EasyOCR into text lines based on horizontal alignment."""
    # ocr_results: list of [ [ [x0,y0], [x1,y1], [x2,y2], [x3,y3] ], text, confidence ]
    if not ocr_results:
        return []
        
    # Sort boxes primarily by top-left y-coordinate
    sorted_boxes = sorted(ocr_results, key=lambda x: x[0][0][1])
    
    lines = []
    current_line = [sorted_boxes[0]]
    current_y = sorted_boxes[0][0][0][1]
    height = abs(sorted_boxes[0][0][2][1] - sorted_boxes[0][0][0][1])
    h_threshold = max(height * 0.7, 10)  # Group if y-difference is small
    
    for box in sorted_boxes[1:]:
        y = box[0][0][1]
        if abs(y - current_y) <= h_threshold:
            current_line.append(box)
        else:
            # Sort the line we just finished by x-coordinate (left to right)
            current_line = sorted(current_line, key=lambda x: x[0][0][0])
            lines.append(" ".join([b[1] for b in current_line]))
            current_line = [box]
            current_y = y
            height = abs(box[0][0][2][1] - box[0][0][0][1])
            h_threshold = max(height * 0.7, 10)
            
    if current_line:
        current_line = sorted(current_line, key=lambda x: x[0][0][0])
        lines.append(" ".join([b[1] for b in current_line]))
        
    return lines


def parse_unstructured_line(line):
    """Extract student details from a raw text line using heuristics and regex."""
    # URN / CRN regex: 7 to 10 digit number
    urn_match = re.search(r'\b(19\d{5,8}|20\d{5,8}|21\d{5,8}|22\d{5,8}|23\d{5,8})\b', line)
    # Phone regex: 10 digits starting with 6-9
    phone_match = re.search(r'\b([6-9]\d{9})\b', line)
    # Branch regex
    branch_match = re.search(r'\b(CSE|ECE|ME|CE|IT|EE|BT|PE|CH|CIVIL|MECH|COMP|ELECT)\b', line, re.IGNORECASE)
    # Section
    sec_match = re.search(r'\b(Sec\s*[A-D]|[A-D])\b', line, re.IGNORECASE)

    urn = urn_match.group(1) if urn_match else ""
    phone = phone_match.group(1) if phone_match else ""
    branch = branch_match.group(1).upper() if branch_match else ""
    section = sec_match.group(1).upper() if sec_match else ""
    
    # clean name
    clean_name = line
    if urn:
        clean_name = clean_name.replace(urn, "")
    if phone:
        clean_name = clean_name.replace(phone, "")
    if branch_match:
        clean_name = re.sub(r'\b(CSE|ECE|ME|CE|IT|EE|BT|PE|CH|CIVIL|MECH|COMP|ELECT)\b', '', clean_name, flags=re.IGNORECASE)
    if sec_match:
        clean_name = re.sub(r'\b(Sec\s*[A-D]|[A-D])\b', '', clean_name, flags=re.IGNORECASE)
        
    # Remove special chars and digits
    clean_name = re.sub(r'[^a-zA-Z\s]', ' ', clean_name)
    words = [w.strip() for w in clean_name.split() if w.strip()]
    
    # Exclude common headers
    exclude_words = {'name', 'urn', 'crn', 'phone', 'mobile', 'branch', 'section', 'present', 'absent', 'nss', 'volunteer'}
    filtered_words = [w for w in words if w.lower() not in exclude_words]
    
    name = ""
    if len(filtered_words) >= 1:
        # Join first few words as candidate student name
        name = " ".join(filtered_words[:3]).title()
        
    return {
        "student_name": name,
        "urn": urn,
        "crn": urn,  # Duplicate URN as CRN default, or look for secondary number
        "phone": phone,
        "branch": branch,
        "section": section,
    }


def parse_tabular_file(file_path, ext):
    """Read a structured CSV/Excel and identify mapping columns."""
    if ext == 'csv':
        df = pd.read_csv(file_path)
    else:
        df = pd.read_excel(file_path)
        
    df.columns = [str(c).strip().lower() for c in df.columns]
    
    # Header mapping heuristics
    col_mapping = {}
    for col in df.columns:
        if any(x in col for x in ['name', 'student', 'volunteer']):
            col_mapping['student_name'] = col
        elif any(x in col for x in ['urn', 'univ', 'university']):
            col_mapping['urn'] = col
        elif any(x in col for x in ['crn', 'class', 'roll']):
            col_mapping['crn'] = col
        elif any(x in col for x in ['phone', 'mobile', 'contact']):
            col_mapping['phone'] = col
        elif any(x in col for x in ['branch', 'dept', 'department']):
            col_mapping['branch'] = col
        elif any(x in col for x in ['section', 'sec']):
            col_mapping['section'] = col
            
    rows = []
    for _, r in df.iterrows():
        # Get values using mapping or empty strings
        name = str(r.get(col_mapping.get('student_name', ''), '')).strip()
        urn = str(r.get(col_mapping.get('urn', ''), '')).strip()
        crn = str(r.get(col_mapping.get('crn', ''), '')).strip()
        phone = str(r.get(col_mapping.get('phone', ''), '')).strip()
        branch = str(r.get(col_mapping.get('branch', ''), '')).strip()
        section = str(r.get(col_mapping.get('section', ''), '')).strip()
        
        # Skip empty rows
        if not name and not urn and not crn:
            continue
            
        # Standardize empty strings
        urn_val = urn.split('.')[0] if urn and urn != 'nan' else ""
        crn_val = crn.split('.')[0] if crn and crn != 'nan' else ""
        phone_val = phone.split('.')[0] if phone and phone != 'nan' else ""
        
        rows.append({
            "student_name": name if name != 'nan' else "",
            "urn": urn_val,
            "crn": crn_val or urn_val,
            "phone": phone_val,
            "branch": branch if branch != 'nan' else "",
            "section": section if section != 'nan' else ""
        })
    return rows


def parse_pdf_file(file_path):
    """Extract text from a digital text PDF, falling back to image OCR if scanned."""
    reader = PdfReader(file_path)
    text_content = []
    
    # Try text extraction first
    for page in reader.pages:
        t = page.extract_text()
        if t and t.strip():
            text_content.append(t)
            
    if text_content:
        # Join all text and split into lines
        full_text = "\n".join(text_content)
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        return [parse_unstructured_line(l) for l in lines]
        
    # If no text extracted, it's a scanned PDF. Extract images and run OCR.
    print("[OCR Helper] Scanned PDF detected, extracting page images...")
    ocr_rows = []
    for page_num, page in enumerate(reader.pages):
        for img_idx, image_file_object in enumerate(page.images):
            # Save raw image data to a temp file
            with tempfile.NamedTemporaryFile(suffix=os.path.splitext(image_file_object.name)[1], delete=False) as temp_img:
                temp_img.write(image_file_object.data)
                temp_img_path = temp_img.name
                
            try:
                # Perform OCR on page image
                reader_ocr = get_ocr_reader()
                results = reader_ocr.readtext(temp_img_path)
                lines = group_ocr_boxes_into_lines(results)
                for l in lines:
                    parsed = parse_unstructured_line(l)
                    if parsed["student_name"] or parsed["urn"] or parsed["phone"]:
                        ocr_rows.append(parsed)
            finally:
                if os.path.exists(temp_img_path):
                    os.remove(temp_img_path)
    return ocr_rows


def parse_image_ocr(file_path):
    """Run EasyOCR on an image file and parse extracted text lines."""
    reader_ocr = get_ocr_reader()
    # Read image text
    results = reader_ocr.readtext(file_path)
    lines = group_ocr_boxes_into_lines(results)
    
    ocr_rows = []
    for l in lines:
        parsed = parse_unstructured_line(l)
        if parsed["student_name"] or parsed["urn"] or parsed["phone"]:
            ocr_rows.append(parsed)
    return ocr_rows


def process_ocr_upload(db, upload_id, file_path, file_type, event_id):
    """Run extraction on uploaded file and compare against Roster (students) and Attendance."""
    try:
        ext = file_type.lower()
        rows = []
        if ext in ['csv', 'xlsx', 'xls']:
            rows = parse_tabular_file(file_path, ext)
        elif ext == 'pdf':
            rows = parse_pdf_file(file_path)
        elif ext in ['png', 'jpg', 'jpeg', 'bmp', 'tiff']:
            rows = parse_image_ocr(file_path)
        else:
            raise ValueError(f"Unsupported file format: {file_type}")
            
        total_rows = len(rows)
        duplicates_count = 0
        
        # Save extracted rows and compare with DB
        for row in rows:
            student_name = row["student_name"]
            urn = row["urn"]
            crn = row["crn"]
            phone = row["phone"]
            branch = row["branch"]
            section = row["section"]
            
            # 1. Match against master student roster
            matched_student = None
            if urn:
                matched_student = db.execute("SELECT * FROM students WHERE urn = ?", (urn,)).fetchone()
            if not matched_student and crn:
                matched_student = db.execute("SELECT * FROM students WHERE crn = ?", (crn,)).fetchone()
            if not matched_student and phone:
                matched_student = db.execute("SELECT * FROM students WHERE phone = ?", (phone,)).fetchone()
            if not matched_student and student_name:
                # Fuzzy or exact name matching
                matched_student = db.execute(
                    "SELECT * FROM students WHERE student_name LIKE ?",
                    (f"%{student_name}%",)
                ).fetchone()
                
            student_id = matched_student["id"] if matched_student else None
            
            # Auto-fill fields from master database if matched
            if matched_student:
                if not student_name: student_name = matched_student["student_name"]
                if not urn: urn = matched_student["urn"]
                if not crn: crn = matched_student["crn"]
                if not phone: phone = matched_student["phone"]
                if not branch: branch = matched_student["branch"]
                if not section: section = matched_student["section"]
                
            # 2. Check if student already marked attendance for this event
            is_dup_in_db = 0
            if event_id:
                dup_query = """SELECT COUNT(*) AS c FROM attendance 
                               WHERE event_id = ? AND (
                                   (crn = ? AND crn IS NOT NULL) OR 
                                   (urn = ? AND urn IS NOT NULL)
                               )"""
                dup_check = db.execute(dup_query, (event_id, crn or None, urn or None)).fetchone()
                if dup_check and dup_check["c"] > 0:
                    is_dup_in_db = 1
                    duplicates_count += 1
                    
            # Save into ocr_extracted_rows
            db.execute(
                """INSERT INTO ocr_extracted_rows (
                    ocr_upload_id, raw_text, extracted_name, extracted_crn, extracted_urn, extracted_phone,
                    confidence, is_duplicate_in_db, matched_student_id, accepted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    upload_id,
                    f"Name: {student_name} | URN: {urn} | Phone: {phone} | Branch: {branch}",
                    student_name or None,
                    crn or None,
                    urn or None,
                    phone or None,
                    0.90 if matched_student else 0.50, # Confidence indicator
                    is_dup_in_db,
                    student_id
                )
            )
            
        # Update upload status
        db.execute(
            """UPDATE ocr_uploads 
               SET status = 'completed', total_rows_detected = ?, total_duplicates = ?
               WHERE id = ?""",
            (total_rows, duplicates_count, upload_id)
        )
        db.commit()
        
    except Exception as e:
        db.execute(
            """UPDATE ocr_uploads 
               SET status = 'failed', error_message = ?
               WHERE id = ?""",
            (str(e), upload_id)
        )
        db.commit()
        print(f"[OCR Helper Error] Upload process failed: {e}")
        raise e
