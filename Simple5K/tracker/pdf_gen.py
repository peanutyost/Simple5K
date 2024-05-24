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

def generate_race_report(filename, race):
  """
  Generates a PDF report for a race with runner lap summaries.

  Args:
    filename (str): The name of the PDF file to create.
    race (object): A Race object representing the race data.
  """
  # Create a canvas object
  c = canvas.Canvas(filename, pagesize=letter)

  # Set font and size
  c.setFont("Helvetica", 14)

  # Add race name with centering
  c.drawCentredString(letter[0] / 2, letter[1] - 50, f"Race: {race.name}")

  # Start y position for content
  y_pos = letter[1] - 100

  # Loop through runners in the race
  for runner in race.runners.all():
    # Check if runner has laps
    if runner.laps.count() > 0:
      # Add runner name and number with formatting
      y_pos -= 20
      c.drawString(50, y_pos, f"Runner: {runner}")
      c.drawString(300, y_pos, f"#{runner.number}")

      # Add table header for lap information
      y_pos -= 20
      c.drawString(50, y_pos, "Lap")
      c.drawString(150, y_pos, "Time")
      c.drawString(250, y_pos, "Duration")
      c.drawString(350, y_pos, "Avg Speed")
      c.line(50, y_pos - 5, letter[0] - 50, y_pos - 5)  # underline header

      # Loop through runner's laps
      for lap in runner.laps.all().order_by('lap'):
        y_pos -= 15
        c.drawString(50, y_pos, str(lap.lap))
        c.drawString(150, y_pos, str(lap.time))
        c.drawString(250, y_pos, str(lap.duration))
        c.drawString(350, y_pos, "{:.2f} m/s".format(lap.average_speed))

      # Add some space before next runner
      y_pos -= 20

    # Check for page break if needed (adjust based on table row height)
    if y_pos < 100:
      c.showPage()
      y_pos = letter[1] - 100

  # Save the PDF
  c.save()

# Example usage (assuming you have a Race object named 'my_race')
#generate_race_report("race_report.pdf", my_race)

def generate_race_report(filename, race):
  spaceAfter = 15
  """
  Generates a professional PDF report for a race with one runner summary per page.

  Args:
    filename (str): The name of the PDF file to create.
    race (object): A Race object representing the race data.
  """
  
  response = HttpResponse(content_type='application/pdf')
  response['Content-Disposition'] = 'filename=' + filename

  buffer = BytesIO()
  # Create a canvas object
  c = canvas.Canvas(buffer, pagesize=letter)

  styles = getSampleStyleSheet()
  heading1 = ParagraphStyle(name="Heading1", fontName="Helvetica-Bold",
                             fontSize=16, alignment=1, leading=20)
  heading2 = ParagraphStyle(name="Heading2", fontName="Helvetica",
                             fontSize=14, alignment=0, leading=15)
  table_body = ParagraphStyle(name="TableBody", fontName="Helvetica",
                               fontSize=11, leading=12)

  # Define margins and usable document area
  margin = 72  # points (1 inch)
  usable_width = letter[0] - 2 * margin
  usable_height = letter[1] - 2 * margin

  # Start y position for content
  y_pos = usable_height - margin
  # Loop through runners in the race
  #for runner in race['runners']:
    # Check if runner has laps
    #if runner['laps']:#.count() > 0:
      # Add a new page for each runner
#  c.showPage()

  # Add race name as heading

  p = Paragraph(f"{race['name']} ", style=heading1)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter * 2
  
  p = Paragraph(f"Finishing Place: {race['runners']['place']} ", style=heading1)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter

  # Add runner name and number with formatting
  p = Paragraph(f"{race['runners']['name']}", style=heading2)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter
  p = Paragraph(f"Number: {race['runners']['number']}", style=heading2)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter  # add extra space
  p = Paragraph(f"Total Time: {race['runners']['total_time']}", style=heading2)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter  # add extra space
  p = Paragraph(f"Avg Speed: {race['runners']['race_avg_speed']} MPH", style=heading2)
  p.wrapOn(c, usable_width, usable_height)
  p.drawOn(c, margin, y_pos)
  y_pos -= spaceAfter  * 2# add extra space

  # Add table header for lap information
  data = [("Lap", "Lap Time", "Avg Speed")]
  table = Table(data, colWidths=[1.5 * inch, 2.5 * inch, 2.5 * inch])
  table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                        ('INNERGRID', (0, 1), (-1, -1), 0.25, colors.black),
                        ('BOX', (0, 0), (-1, -1), 0.25, colors.black),
                        ]))
  table.wrapOn(c, usable_width, usable_height)
  table.drawOn(c, margin, y_pos)
  y_pos -= 30 + 5  # add some space after header

  # Loop through runner's laps
  i = 0
  for lap in race['runners']['laps']:
    i += 1
    data = [[str(race['runners']['laps'][i]['lap']), str(race['runners']['laps'][i]['duration']), str(race['runners']['laps'][i]['average_speed'])]]
    table = Table(data, colWidths=[1.5 * inch, 2.5 * inch, 2.5 * inch])
    table.setStyle(TableStyle([('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
                        [colors.white, colors.lightgrey])
                        ])
                        )
    table.wrapOn(c, usable_width, usable_height)
    table.drawOn(c, margin, y_pos)
    y_pos -= 30

  # Ensure content fits on the page and add a new page if needed
  if y_pos < margin:
    c.showPage()
    
  c.save()
  buffer.seek(SEEK_SET)  # Reset buffer position
  response.write(buffer.getvalue())

  return response