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
from reportlab.lib.colors import HexColor
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

    def draw_box(canvas_obj, x, y, width, height, text_lines, top_padding=0.2 * inch):
        """Draws a box with text inside, with adjustable top padding."""
        canvas_obj.rect(x, y, width, height)
        # Calculate the starting y-position for the text, incorporating top_padding.
        text_y = y + height - top_padding
        for line in text_lines:
            canvas_obj.setFont("Helvetica", 11)
            canvas_obj.setFillColor(colors.black)  # added in case color changes
            canvas_obj.drawString(x + 0.1 * inch, text_y, line)
            text_y -= 0.17 * inch  # Line spacing.  Keep this separate from top_padding.

    # --- Background Image (Logo) ---
    if race_data['race']['logo'] is not None:
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

    # --- Top Left Box: Runner Information ---
    runner_box_x = margin
    runner_box_y = usable_height - .5 * inch  # Adjust y position more clearly
    runner_box_width = 2 * inch
    runner_box_height = 1.3 * inch
    runner_info = [
        f"Name: {race_data['runner']['name']}",
        f"Number: {race_data['runner']['number']}",
        f"Gender: {race_data['runner']['gender']}",
        f"Type: {race_data['runner']['type']}",
        f"Total Time: {race_data['runner']['total_time']}",
        f"Avg Pace: {race_data['runner']['avg_pace']}",
        f"Avg Speed: {race_data['runner']['race_avg_speed']} mph",
    ]
    draw_box(c, runner_box_x, runner_box_y, runner_box_width, runner_box_height, runner_info, top_padding=0.17 * inch)

    # --- Top Right: Race Name and Finishing Place ---
    race_info_x = letter[0] - margin - 3 * inch
    race_info_y = usable_height + .3 * inch  # Start a little lower than runner's box
    c.setFont("Helvetica-Bold", 26)
    c.drawRightString(race_info_x + 2.5 * inch, race_info_y, race_data['race']['name'])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(race_info_x + 2.5 * inch, race_info_y - 0.4 * inch, f"Finishing Place: {race_data['runner']['place']}")

    # --- Lap Times Table ---
    y_pos = runner_box_y - spaceAfter - 0.4 * inch
    y_pos = draw_paragraph("Lap Stats", heading3, c, margin, y_pos)  # Reuse y_pos
    y_pos += spaceAfter

    data = [["Lap", "Lap Time", "Avg. Pace", "Avg. Speed (mph)"],]
    for lap in race_data['laps']:
        data.append([lap['lap'], lap['time'], lap['average_pace'], f"{lap['average_speed']:.2f}"],)

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
    y_pos = y_pos - spaceAfter - 0.6 * inch
    y_pos = draw_paragraph("Placement Within Age Bracket", heading3, c, margin, y_pos)  # Reuse y_pos

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
    bracket_table.drawOn(c, margin, y_pos - spaceAfter - bracket_table_height)
    y_pos -= bracket_table_height + spaceAfter

    y_pos = y_pos - spaceAfter - 0.6 * inch
    y_pos = draw_paragraph("Those Who Finished Before and After You", heading3, c, margin, y_pos)

    # --- Competitor Table ---
    data = [["Name", "Total Time"]]
    if race_data['competitors']['faster_runners']:
        data.append(['Before', ''])
    for competitor in race_data['competitors']['faster_runners']:
        data.append([competitor[0], competitor[1]])
    if race_data['competitors']['slower_runners']:
        data.append(['After', ''])
    for competitor in race_data['competitors']['slower_runners']:
        data.append([competitor[0], competitor[1]])

    competitor_table = Table(data, colWidths=[2 * inch, 2 * inch])
    competitor_table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                                          ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                                          ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                                          ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                                          ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                                          ('GRID', (0, 0), (-1, -1), 0.5, colors.black)]))

    competitor_table_width, competitor_table_height = competitor_table.wrapOn(c, usable_width, usable_height)
    competitor_table.drawOn(c, margin, y_pos - competitor_table_height - spaceAfter)  # Draw the table

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
                            leftMargin=0.5*inch, rightMargin=0.5*inch,
                            topMargin=0.5*inch, bottomMargin=0.5*inch)
    styles = getSampleStyleSheet()
    story = []

    # Title
    title = f"Runner List: {race_obj.name}"
    story.append(Paragraph(title, styles['h1']))
    story.append(Spacer(1, 0.2*inch))

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
            runner.get_gender_display() if runner.gender else 'N/A', # Use get_..._display for choices
            runner.get_shirt_size_display(),
            runner.get_type_display() if runner.type else 'N/A',
            runner.id
        ])

    # Create Table and Style
    table = Table(data, colWidths=[0.5*inch, 0.8*inch, 1.5*inch, 1.5*inch, 0.8*inch, 1.2*inch, 0.8*inch]) # Adjust widths as needed

    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), # Vertical alignment
        # Specific alignment for names if needed
        ('ALIGN', (2, 1), (3, -1), 'LEFT'), # Align names left
        ('LEFTPADDING', (2, 1), (3, -1), 6), # Add padding to names
    ])

    table.setStyle(style)
    story.append(table)

    # Build the PDF
    doc.build(story)
    # The buffer now contains the PDF data
