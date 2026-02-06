from io import BytesIO, SEEK_SET
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Frame,
    Image,
    Spacer
)
from django.http import HttpResponse
from datetime import date, timedelta  # Import timedelta
from reportlab.pdfbase import pdfmetrics   # text width, height, font
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, Color
from PIL import Image as PILImage  # Use PIL for image manipulation


def generate_race_report(filename, race_data, return_type):
    """
    Generates a professional PDF report for a race with one runner summary per page,
    and returns either a Django HttpResponse or the raw PDF file content, based on the return_type.

    Args:
        filename (str): The desired filename for the PDF report.
        race_data (dict): A dictionary containing the race data.
        return_type (str, optional):  Determines the return type.
            - "response" (default): Returns a Django HttpResponse object.
            - "file": Returns the raw PDF file content as bytes.

    Returns:
        HttpResponse (if return_type="response") or bytes (if return_type="file"):
        The generated PDF report as a Django HttpResponse or raw bytes.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)

    # --- Define Styles ---
    styles = getSampleStyleSheet()
    heading1 = ParagraphStyle(name="Heading1", fontName="Helvetica-Bold", fontSize=16, alignment=1, leading=20)
    heading2 = ParagraphStyle(name="Heading2", fontName="Helvetica", fontSize=12, alignment=0, leading=15)
    heading3 = ParagraphStyle(name="Heading3", fontName="Helvetica-Bold", fontSize=14, alignment=0, leading=18)
    table_body = ParagraphStyle(name="TableBody", fontName="Helvetica", fontSize=10, leading=12)
    small = ParagraphStyle(name="Small", fontName="Helvetica", fontSize=8, leading=10)

    # --- Modern color palette ---
    header_bg = Color(180 / 255, 121 / 255, 43 / 255, alpha=0.7)  # rgba(180,121,43,0.7)
    header_text = HexColor('#0f172a')
    section_gray = HexColor('#64748b')
    grid_light = HexColor('#e2e8f0')
    row_alt = HexColor('#f8fafc')
    row_white = colors.white

    # --- Define Layout Constants ---
    margin = inch
    usable_width = letter[0] - 2 * margin
    usable_height = letter[1] - 2 * margin
    y_pos = usable_height
    spaceAfter = 0.12 * inch
    table_width_uniform = 4.5 * inch  # All tables same width for a classy, consistent look

    def draw_paragraph(text, style, canvas_obj, x, y):
        """Draws a paragraph and returns the updated y_pos."""
        p = Paragraph(text, style)
        p.wrapOn(canvas_obj, usable_width, usable_height)
        p.drawOn(canvas_obj, x, y - p.height)
        return y - p.height

    center_x = margin + usable_width / 2

    def draw_section_title(canvas_obj, text, y, full_width):
        """Draw section title centered with a thin line under it."""
        canvas_obj.setFillColor(section_gray)
        canvas_obj.setFont("Helvetica-Bold", 10)
        canvas_obj.drawCentredString(center_x, y, text.upper())
        canvas_obj.setStrokeColor(grid_light)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.line(margin, y - 0.1 * inch, margin + full_width, y - 0.1 * inch)
        return y - 0.2 * inch

    def draw_runner_card(canvas_obj, x, y, width, height, name, detail_lines, top_padding=0.3 * inch):
        """Draws a card-style box: name in large type, then detail lines. top_padding = space from top of box to first line."""
        canvas_obj.setFillColor(row_alt)
        canvas_obj.rect(x, y, width, height, fill=1, stroke=0)
        canvas_obj.setStrokeColor(grid_light)
        canvas_obj.setLineWidth(0.5)
        canvas_obj.rect(x, y, width, height, fill=0, stroke=1)
        text_x = x + 0.2 * inch
        text_y = y + height - top_padding
        canvas_obj.setFillColor(colors.black)
        canvas_obj.setFont("Helvetica-Bold", 16)
        canvas_obj.drawString(text_x, text_y, name)
        text_y -= 0.24 * inch
        canvas_obj.setFont("Helvetica", 10)
        for line in detail_lines:
            canvas_obj.drawString(text_x, text_y, line)
            text_y -= 0.17 * inch

    # --- Background Image (Logo) ---
    if race_data['race'].get('logo'):
        try:
            # Open the image using PIL and convert to RGB
            pil_img = PILImage.open(race_data['race']['logo']).convert("RGB")

            # Reduce image dimensions for background use
            max_size = (letter[0], letter[1])  # Page size
            pil_img.thumbnail(max_size, PILImage.LANCZOS)   # Use LANCZOS for better downsampling

            # Convert to ReportLab-compatible image
            img_buffer = BytesIO()
            pil_img.save(img_buffer, format='PNG')  # save it as PNG.
            img_buffer.seek(0)
            img = Image(img_buffer)   # Pass the bytesIO buffer.
            img_width, img_height = img.wrapOn(c, letter[0], letter[1])  # scale image

            # Center the image on the page.
            x = (letter[0] - img_width) / 2
            y = (letter[1] - img_height) / 2

            # Draw the image with transparency (alpha).
            c.saveState()
            c.setFillAlpha(0.15)  # Control transparency
            c.drawImage(race_data['race']['logo'], x, y, width=img_width, height=img_height, mask='auto')
            c.restoreState()

        except (FileNotFoundError, OSError, AttributeError) as e:
            print(f"Error loading or drawing background image: {e}. Skipping background.")
        except Exception as e:  # General exception for other image-related problems
            print(f"An unexpected error occurred with the image: {e}. Skipping background.")

    # --- Race name block (right, high on page, larger) ---
    race_info_x = letter[0] - margin
    race_info_y = usable_height + 0.55 * inch
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 24)
    c.drawRightString(race_info_x, race_info_y, race_data['race']['name'])
    c.setFont("Helvetica", 11)
    c.setFillColor(section_gray)
    race_date = race_data['race'].get('date', '')
    if race_data['race'].get('distance'):
        c.drawRightString(race_info_x, race_info_y - 0.32 * inch, f"{race_date}  ·  {race_data['race']['distance']} m")
    else:
        c.drawRightString(race_info_x, race_info_y - 0.32 * inch, race_date)
    rs = race_data['runner']
    place = rs.get('place', 'N/A')
    total_finishers = race_data.get('total_finishers')
    if total_finishers is not None and place != 'N/A':
        place_str = f"Place: {place} of {total_finishers}"
    else:
        place_str = f"Place: {place}"
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 16)
    c.drawRightString(race_info_x, race_info_y - 0.64 * inch, place_str)

    # --- Runner summary card (left, compact) ---
    runner_box_x = margin
    runner_box_y = usable_height - 0.18 * inch
    runner_box_width = 2.6 * inch
    runner_box_height = 1.28 * inch
    avg_speed_str = f"{rs['race_avg_speed']:.2f} mph" if isinstance(rs.get('race_avg_speed'), (int, float)) else f"{rs.get('race_avg_speed', 'N/A')}"
    runner_name = (rs.get('name') or '').upper()
    runner_details = [
        f"Bib #{rs['number']}  ·  {rs['type']}",
        f"Total time   {rs['total_time']}",
        f"Avg pace   {rs['avg_pace']}",
        f"Avg speed   {avg_speed_str}",
    ]
    draw_runner_card(c, runner_box_x, runner_box_y, runner_box_width, runner_box_height, runner_name, runner_details, top_padding=0.3 * inch)

    # --- Lap Times Table (centered) ---
    y_pos = runner_box_y - spaceAfter - 0.2 * inch
    y_pos = draw_section_title(c, "Lap stats", y_pos, usable_width)
    y_pos -= 0.1 * inch

    data = [["Lap", "Lap time", "Avg. pace", "Avg. speed (mph)"]]
    for lap in race_data['laps']:
        data.append([str(lap['lap']), lap['time'], lap['average_pace'], f"{lap['average_speed']:.2f}"])

    lap_col_widths = [0.72 * inch, 1.26 * inch, 1.26 * inch, 1.26 * inch]  # total = table_width_uniform
    table = Table(data, colWidths=lap_col_widths)
    lap_style = [
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), header_text),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, grid_light),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]
    for i in range(1, len(data)):
        bg = row_alt if i % 2 == 0 else row_white
        lap_style.append(('BACKGROUND', (0, i), (-1, i), bg))
    table.setStyle(TableStyle(lap_style))

    _, table_height = table.wrapOn(c, usable_width, usable_height)
    table.drawOn(c, center_x - table_width_uniform / 2, y_pos - table_height)
    y_pos -= table_height + spaceAfter

    # --- Age Bracket (centered) ---
    y_pos = y_pos - 0.2 * inch
    y_pos = draw_section_title(c, "Age group", y_pos, usable_width)
    y_pos -= 0.1 * inch

    rs = race_data['runner']
    age_place = rs.get('age_group_placement', 'N/A')
    age_total = rs.get('age_group_total')
    if age_total is not None and age_place != 'N/A':
        place_str = f"{age_place} of {age_total}"
    else:
        place_str = str(age_place)
    data = [["Age group", "Place"]]
    data.append([str(rs['age_bracket']), place_str])

    bracket_table = Table(data, colWidths=[2.5 * inch, 2 * inch])  # total = table_width_uniform
    bracket_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), header_text),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('BACKGROUND', (0, 1), (-1, 1), row_white),
        ('TOPPADDING', (0, 1), (-1, 1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, grid_light),
    ]))
    _, bracket_table_height = bracket_table.wrapOn(c, usable_width, usable_height)
    bracket_table.drawOn(c, center_x - table_width_uniform / 2, y_pos - bracket_table_height)
    y_pos -= bracket_table_height + spaceAfter

    # --- Nearby finishers (centered) ---
    y_pos = y_pos - 0.18 * inch
    y_pos = draw_section_title(c, "Finished just before & after you", y_pos, usable_width)
    y_pos -= 0.1 * inch

    data = [["Name", "Total time"]]
    if race_data['competitors']['faster_runners']:
        data.append(['— Before you —', ''])
        for competitor in race_data['competitors']['faster_runners']:
            data.append([competitor[0], competitor[1]])
    if race_data['competitors']['slower_runners']:
        data.append(['— After you —', ''])
        for competitor in race_data['competitors']['slower_runners']:
            data.append([competitor[0], competitor[1]])

    competitor_table = Table(data, colWidths=[2.75 * inch, 1.75 * inch])  # total = table_width_uniform
    comp_style = [
        ('BACKGROUND', (0, 0), (-1, 0), header_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), header_text),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TOPPADDING', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 10),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('GRID', (0, 0), (-1, -1), 0.5, grid_light),
        ('LEFTPADDING', (0, 0), (0, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
    ]
    for i in range(1, len(data)):
        if '—' in str(data[i][0]):
            comp_style.append(('BACKGROUND', (0, i), (-1, i), row_alt))
            comp_style.append(('FONTNAME', (0, i), (-1, i), 'Helvetica-Bold'))
        else:
            comp_style.append(('BACKGROUND', (0, i), (-1, i), row_white if i % 2 == 0 else row_alt))
    competitor_table.setStyle(TableStyle(comp_style))

    _, competitor_table_height = competitor_table.wrapOn(c, usable_width, usable_height)
    competitor_table.drawOn(c, center_x - table_width_uniform / 2, y_pos - competitor_table_height)

    c.save()  # complete drawing
    buffer.seek(SEEK_SET)
    pdf_data = buffer.getvalue()

    if return_type.lower() == "response":
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'filename="{filename}"'
        response.write(pdf_data)
        return response
    elif return_type.lower() == "file":
        return pdf_data
    else:
        raise ValueError("Invalid return_type.  Must be 'response' or 'file'.")


def create_runner_pdf(buffer, race_obj, runners_queryset):
    """Generates a PDF report of runners for a given race."""
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title = f"Runner List: {race_obj.name}"
    story.append(Paragraph(title, styles['h1']))
    story.append(Spacer(1, 0.2 * inch))

    # Table Data Preparation
    # Header Row
    header = ['Number', 'First Name', 'Last Name', 'Gender', 'Shirt Size', 'Type', 'Order']
    data = [header]

    # Data Rows
    for runner in runners_queryset:
        data.append([
            runner.number if runner.number is not None else 'N/A',
            runner.first_name,
            runner.last_name,
            runner.get_gender_display() if runner.gender else 'N/A',  # Use get_..._display for choices
            runner.get_shirt_size_display(),
            runner.get_type_display() if runner.type else 'N/A',
            runner.id
        ])

    # Create Table and Style
    # Adjust widths as needed
    table = Table(data, colWidths=[0.5 * inch, 0.8 * inch, 1.5 * inch, 1.5 * inch, 0.8 * inch, 1.2 * inch, 0.8 * inch])

    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),  # Vertical alignment
        # Specific alignment for names if needed
        ('ALIGN', (2, 1), (3, -1), 'LEFT'),  # Align names left
        ('LEFTPADDING', (2, 1), (3, -1), 6),  # Add padding to names
    ])

    table.setStyle(style)
    story.append(table)

    # Build the PDF
    doc.build(story)
    # The buffer now contains the PDF data


def generate_race_summary_pdf(buffer, summary_data):
    """
    Generates a race summary PDF with two sections: Women and Men.
    Each section lists runners in finish order with name, number, fastest/slowest lap (and lap #),
    overall time, age group, and age group placement.
    summary_data: dict with 'race_name', 'females' (list of runner dicts), 'males' (list of runner dicts).
    Each runner dict: name, number, fastest_lap_time, fastest_lap_num, slowest_lap_time, slowest_lap_num,
    overall_time, overall_place, age_group, age_group_place.
    """
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    styles = getSampleStyleSheet()
    story = []

    title = Paragraph(f"Race Summary: {summary_data['race_name']}", styles['Title'])
    story.append(title)
    story.append(Spacer(1, 0.3 * inch))

    def _format_duration(val):
        if val is None or val == '' or val == 'N/A':
            return 'N/A'
        if hasattr(val, 'total_seconds'):
            secs = int(round(val.total_seconds()))
            return str(timedelta(seconds=secs))
        return str(val)

    def _section_table(section_title, runners_list):
        header = [
            'Place', 'Name', 'No.', 'Fastest Lap', 'Lap', 'Slowest Lap', 'Lap',
            'Overall Time', 'Age Group', 'Age Grp'
        ]
        data = [header]
        for r in runners_list:
            data.append([
                str(r.get('overall_place') or '—'),
                r.get('name') or '—',
                str(r.get('number') or '—'),
                _format_duration(r.get('fastest_lap_time')),
                str(r.get('fastest_lap_num') or '—'),
                _format_duration(r.get('slowest_lap_time')),
                str(r.get('slowest_lap_num') or '—'),
                _format_duration(r.get('overall_time')),
                r.get('age_group') or '—',
                str(r.get('age_group_place') or '—'),
            ])
        col_widths = [
            0.5 * inch, 1.35 * inch, 0.4 * inch,
            0.85 * inch, 0.35 * inch, 0.85 * inch, 0.35 * inch,
            0.85 * inch, 0.65 * inch, 0.5 * inch
        ]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 7),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('LEFTPADDING', (1, 1), (1, -1), 4),
        ]))
        story.append(Paragraph(section_title, styles['Heading2']))
        story.append(Spacer(1, 0.15 * inch))
        story.append(table)
        story.append(Spacer(1, 0.35 * inch))

    if summary_data.get('females'):
        _section_table('Women', summary_data['females'])
    if summary_data.get('males'):
        _section_table('Men', summary_data['males'])

    if not summary_data.get('females') and not summary_data.get('males'):
        story.append(Paragraph('No finishers with gender recorded for this race.', styles['Normal']))

    doc.build(story)
