"""
utils/pdf_generator.py
Generates professional PDF attendance reports using reportlab.
Includes stylized header tables, cell wrapping, and automatic page numbers.
"""

from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas

class NumberedCanvas(canvas.Canvas):
    """Canvas helper to compute total pages dynamically and add footers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            super().showPage()
        super().save()

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 9)
        self.setFillColor(colors.HexColor("#555555"))
        
        # Draw a footer line
        self.setStrokeColor(colors.HexColor("#DDDDDD"))
        self.setLineWidth(0.5)
        self.line(36, 40, self._pagesize[0] - 36, 40)
        
        # Footer text
        footer_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(self._pagesize[0] - 36, 25, footer_text)
        self.drawString(36, 25, "NSS Attendance Management System - Official Report")
        self.restoreState()


def export_attendance_pdf(rows, event_title, filepath):
    """Generate a landscape-oriented professional PDF report of attendance."""
    # Use landscape letter size for landscape orientation (fits columns easily)
    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(letter),
        leftMargin=36,
        rightMargin=36,
        topMargin=36,
        bottomMargin=54
    )
    
    styles = getSampleStyleSheet()
    
    # Custom Styles
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        textColor=colors.HexColor("#1F4D36"),
        spaceAfter=6
    )
    
    meta_style = ParagraphStyle(
        'DocMeta',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=9,
        textColor=colors.HexColor("#555555"),
        spaceAfter=15
    )
    
    cell_header_style = ParagraphStyle(
        'CellHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        textColor=colors.white,
        alignment=1 # Center
    )
    
    cell_data_style = ParagraphStyle(
        'CellData',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        textColor=colors.HexColor("#333333")
    )
    
    cell_data_center = ParagraphStyle(
        'CellDataCenter',
        parent=cell_data_style,
        alignment=1 # Center
    )

    story = []
    
    # 1. Title & Metadata Header
    story.append(Paragraph(f"NSS Attendance Report: {event_title or 'All Events'}", title_style))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    story.append(Paragraph(f"Generated on: {now_str} | Total Records: {len(rows)}", meta_style))
    
    # 2. Table Data
    headers = [
        "No.", "Student Name", "Branch", "CRN", "URN", 
        "Phone", "NSS", "Mode", "Location Address", "Time"
    ]
    
    # Columns widths: total printable landscape width is 792 - 72 = 720
    col_widths = [25, 110, 60, 50, 55, 60, 25, 35, 230, 70]
    
    table_data = [[Paragraph(h, cell_header_style) for h in headers]]
    
    for idx, r in enumerate(rows, 1):
        # Format time
        created_at = r.get("created_at", "")
        time_str = "-"
        if created_at:
            parts = created_at.split()
            time_str = parts[0] # Show date
            if len(parts) > 1:
                # Add hour:minute
                time_str += f"\n{parts[1].split('.')[0]}"
                
        address = r.get("location_address") or "-"
        if address.startswith("Coordinates:"):
            # short coordinate representation
            address = address.split("(")[0].strip()
            
        vals = [
            str(idx),
            r.get("student_name", ""),
            r.get("branch", "-") or "-",
            r.get("crn", "-") or "-",
            r.get("urn", "-") or "-",
            r.get("phone", ""),
            "Yes" if r.get("is_nss_volunteer") == 1 else "No",
            r.get("attendance_mode", "").upper(),
            address,
            time_str
        ]
        
        row_cells = []
        for i, val in enumerate(vals):
            # Align center for meta columns
            style_to_use = cell_data_center if i in [0, 2, 3, 4, 5, 6, 7, 9] else cell_data_style
            row_cells.append(Paragraph(str(val).replace("\n", "<br/>"), style_to_use))
            
        table_data.append(row_cells)
        
    # 3. Create Table
    t = Table(table_data, colWidths=col_widths, repeatRows=1)
    
    # Stylize Table
    t_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1F4D36")),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('TOPPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#EAEAEA")),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FBF9")]),
        ('TOPPADDING', (0, 1), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
    ])
    
    t.setStyle(t_style)
    story.append(t)
    
    # 4. Build document
    doc.build(story, canvasmaker=NumberedCanvas)
