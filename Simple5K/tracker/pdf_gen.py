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


def generate_race_report(filename, race_data):
    """
    Generates a professional PDF report for a race with one runner summary per page.
    """

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'filename="{filename}"'
    buffer = BytesIO()

    # Create a canvas object
    c = canvas.Canvas(buffer, pagesize=letter)

    # Define styles
    styles = getSampleStyleSheet()

    heading1 = ParagraphStyle(
        name="Heading1", fontName="Helvetica-Bold", fontSize=16, alignment=1, leading=20)  # Centered Aligned
    heading2 = ParagraphStyle(
        name="Heading2", fontName="Helvetica", fontSize=12, alignment=0, leading=15)  # Left Aligned
    heading3 = ParagraphStyle(
        name="Heading3", fontName="Helvetica-Bold", fontSize=14, alignment=0, leading=18)  # Section Headers
    table_body = ParagraphStyle(
        name="TableBody", fontName="Helvetica", fontSize=10, leading=12)
    small = ParagraphStyle(
        name="Small", fontName="Helvetica", fontSize=8, leading=10)

    # Define margins and usable document area
    margin = 72  # points (1 inch)
    usable_width = letter[0] - 2 * margin
    usable_height = letter[1] - 2 * margin
    y_pos = usable_height - margin

    def draw_paragraph(text, style, canvas_obj, x, y):
        p = Paragraph(text, style)
        p.wrapOn(canvas_obj, usable_width, usable_height)
        p.drawOn(canvas_obj, x, y - p.height)  # Adjust y position
        return y - p.height

    spaceAfter = 15

    # Add Race Information
    y_pos = draw_paragraph(race_data['race']['name'], heading1, c, margin, y_pos)
    y_pos -= spaceAfter * 0.75
    y_pos = draw_paragraph(f"Race Date: {race_data['race']['date']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Race Distance: {race_data['race']['distance']} meters", heading2, c, margin, y_pos)
    y_pos -= spaceAfter

    # Add Runner Information
    y_pos = draw_paragraph("Runner Information", heading3, c, margin, y_pos)
    y_pos -= spaceAfter / 2
    y_pos = draw_paragraph(f"Runner Name: {race_data['runner']['name']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Runner Number: {race_data['runner']['number']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Age Bracket: {race_data['runner']['age_bracket']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Gender: {race_data['runner']['gender']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Runner Type: {race_data['runner']['type']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Shirt Size: {race_data['runner']['shirt_size']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Total Time: {race_data['runner']['total_time']}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Avg Speed: {race_data['runner']['race_avg_speed']} m/s", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Finishing Place: {race_data['runner']['place']}", heading2, c, margin, y_pos)
    y_pos -= spaceAfter

    # Add Competitor Information
    y_pos = draw_paragraph("Competitor Information", heading3, c, margin, y_pos)
    y_pos -= spaceAfter / 2

    y_pos = draw_paragraph(f"Faster Runners: {', '.join(race_data['competitors']['faster_runners'])}", heading2, c, margin, y_pos)
    y_pos = draw_paragraph(f"Slower Runners: {', '.join(race_data['competitors']['slower_runners'])}", heading2, c, margin, y_pos)

    y_pos -= spaceAfter

    # Add Lap Data Table
    y_pos = draw_paragraph("Lap Information", heading3, c, margin, y_pos)
    y_pos -= spaceAfter / 2
    # Table Header
    data = [["Lap", "Lap Time", "Avg Speed (m/s)"]]
    table = Table(data, colWidths=[1.5 * inch, 2 * inch, 2 * inch])
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                               ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                               ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                               ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                               ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                               ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                               ('GRID', (0, 0), (-1, -1), 1, colors.black)]))

    # Calculate table height *before* drawing
    table_width, table_height = table.wrapOn(c, usable_width, usable_height)
    table.drawOn(c, margin, y_pos - table_height)  # Draw it on the page
    y_pos -= table_height + 5  # Adjust position for what comes next

    # Table Data
    for lap in race_data['laps']:
        data = [[lap['lap'], lap['time'], f"{lap['average_speed']:.2f}"]]
        table = Table(data, colWidths=[1.5 * inch, 2 * inch, 2 * inch])
        table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                                   ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))

        # Calculate table height *before* drawing
        table_width, table_height = table.wrapOn(c, usable_width, usable_height)
        table.drawOn(c, margin, y_pos - table_height)
        y_pos -= table_height

        if y_pos < margin:
            c.showPage()
            y_pos = usable_height - margin

    c.save()
    buffer.seek(SEEK_SET)
    response.write(buffer.getvalue())
    return response
