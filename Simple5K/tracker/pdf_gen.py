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
    Image
)
from django.http import HttpResponse
from datetime import date


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
    # --- Define Layout Constants ---
    margin = inch
    usable_width = letter[0] - 2 * margin
    usable_height = letter[1] - 2 * margin
    y_pos = usable_height
    spaceAfter = 0.2 * inch  # Using inch for larger consistent spacing
    def draw_paragraph(text, style, canvas_obj, x, y):
        """Draws a paragraph and returns the updated y_pos."""
        p = Paragraph(text, style)
        p.wrapOn(canvas_obj, usable_width, usable_height)
        p.drawOn(canvas_obj, x, y - p.height)
        return y - p.height
    def draw_box(canvas_obj, x, y, width, height, text_lines):
        """Draws a box with text inside."""
        canvas_obj.rect(x, y, width, height)
        text_y = y + height - 0.1 * inch
        for line in text_lines:
            canvas_obj.setFont("Helvetica", 10)
            canvas_obj.drawString(x + 0.1 * inch, text_y, line)
            text_y -= 0.15 * inch
    # --- Top Left Box: Runner Information ---
    runner_box_x = margin
    runner_box_y = usable_height - .5 * inch  # Adjust y position more clearly
    runner_box_width = 2 * inch
    runner_box_height = 1.1 * inch
    runner_info = [
        f"Type: {race_data['runner']['type']}",
        f"Name: {race_data['runner']['name']}",
        f"gender: {race_data['runner']['gender']}",
        f"Number: {race_data['runner']['number']}",
        f"Total Time: {race_data['runner']['total_time']}",
        f"Avg Speed: {race_data['runner']['race_avg_speed']} mph",
        f"Avg Pace: {race_data['runner']['avg_pace']}"
    ]
    draw_box(c, runner_box_x, runner_box_y, runner_box_width, runner_box_height, runner_info)
    # --- Top Right: Race Name and Finishing Place ---
    race_info_x = letter[0] - margin - 3 * inch
    race_info_y = usable_height - .01 * inch  # Start a little lower than runner's box
    c.setFont("Helvetica-Bold", 24)
    c.drawRightString(race_info_x + 2.5 * inch, race_info_y, race_data['race']['name'])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(race_info_x + 2.5 * inch, race_info_y - 0.4 * inch, f"Finishing Place: {race_data['runner']['place']}")
    # --- Lap Times Table ---
    y_pos = runner_box_y - spaceAfter
    y_pos = draw_paragraph("Lap Information", heading3, c, margin, y_pos)  # Reuse y_pos
    y_pos -= spaceAfter / 2
    data = [["Lap", "Lap Time", "Avg Speed (m/s)"]]
    for lap in race_data['laps']:
        data.append([lap['lap'], lap['time'], f"{lap['average_speed']:.2f}"])
    lap_table_x = margin
    lap_table_y = y_pos - 3 * inch  # Adjust positioning for the table
    table = Table(data, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black)
    ]))
    table_width, table_height = table.wrapOn(c, usable_width, usable_height)
    table.drawOn(c, lap_table_x, y_pos - table_height - 2 * spaceAfter)  # Draw the table directly, not relying on draw_paragraph
    y_pos -= table_height + spaceAfter
    # --- Age Bracket Table ---
    y_pos = y_pos - spaceAfter
    data = [["Age Bracket", "Placement"]]
    data.append([race_data['runner']['age_bracket'], race_data['runner']['age_group_placement']])
    bracket_table = Table(data, colWidths=[2 * inch, 2 * inch])
    bracket_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                                       ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                       ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                                       ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                       ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                                       ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))
    bracket_table_width, bracket_table_height = bracket_table.wrapOn(c, usable_width, usable_height)
    bracket_table.drawOn(c, margin, y_pos - table_height - 2 * spaceAfter - bracket_table_height)
    y_pos -= bracket_table_height + spaceAfter
    # --- Competitor Table ---
    data = [["Name", "Total Time"]]
    for competitor in race_data['competitors']['faster_runners']:
        data.append([competitor[0], competitor[1]])
    data.append(['', ''])
    for competitor in race_data['competitors']['slower_runners']:
        data.append([competitor[0], competitor[1]])
    competitor_table = Table(data, colWidths=[1 * inch, 3 * inch])
    competitor_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                                          ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                          ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                                          ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                          ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                                          ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))
    competitor_table_width, competitor_table_height = competitor_table.wrapOn(c, usable_width, usable_height)
    competitor_table.drawOn(c, margin, y_pos - table_height - competitor_table_height - bracket_table_height - 3 * spaceAfter)  # Draw the table
    c.save()  # complete drawing
    buffer.seek(SEEK_SET)
    pdf_data = buffer.getvalue()
    if return_type.lower() == "response":
        from django.http import HttpResponse
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'filename="{filename}"'
        response.write(pdf_data)
        return response
    elif return_type.lower() == "file":
        return pdf_data
    else:
        raise ValueError("Invalid return_type.  Must be 'response' or 'file'.")
