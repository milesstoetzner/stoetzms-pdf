"""Generate the fictitious source PDFs and images used by the example project.

    python examples/make_sample_documents.py

The example's documents/ folder is committed, so this is only needed to
recreate them. Every document is marked as a sample and contains no real
personal data. They deliberately mix page sizes and orientations.
"""

from pathlib import Path

import weasyprint
from PIL import Image, ImageDraw

HERE = Path(__file__).parent / "application" / "documents"

STYLE = """
@page { size: %(size)s; margin: 18mm; }
body { font-family: Georgia, "Times New Roman", serif; font-size: 11pt; color: #000; }
h1 { font-size: 18pt; margin: 0 0 6mm; }
h2 { font-size: 12pt; margin: 8mm 0 3mm; }
.sample { position: fixed; top: -10mm; right: 0; font: 8pt sans-serif; color: #000;
          letter-spacing: .1em; }
table { border-collapse: collapse; width: 100%%; }
td, th { border: 0.5pt solid #000; padding: 2mm 3mm; text-align: left; }
.box { border: 0.75pt solid #000; padding: 5mm; margin: 4mm 0; }
a { color: #000; }
.page { break-after: page; }
.page:last-child { break-after: auto; }
"""


def write(name: str, size: str, body: str) -> None:
    html = (f"<html><head><style>{STYLE % {'size': size}}</style></head><body>"
            f'<div class="sample">SAMPLE DOCUMENT</div>{body}</body></html>')
    weasyprint.HTML(string=html).write_pdf(HERE / name)
    print("wrote", HERE / name)


def write_image(name: str, size: tuple[int, int], title: str, lines: list[str]) -> None:
    """A black-and-white placeholder 'scan' with a frame, a title and text lines."""
    width, height = size
    image = Image.new("L", size, 255)
    draw = ImageDraw.Draw(image)
    unit = min(width, height) // 40
    draw.rectangle([unit, unit, width - unit, height - unit], outline=0, width=max(2, unit // 3))
    draw.text((width - 3 * unit, 3 * unit), "SAMPLE", fill=0, font_size=2 * unit, anchor="ra")
    draw.text((4 * unit, 8 * unit), title, fill=0, font_size=3 * unit)
    for index, line in enumerate(lines):
        draw.text((4 * unit, (16 + 4 * index) * unit), line, fill=0, font_size=2 * unit)
    path = HERE / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".jpg":
        image.save(path, "JPEG", quality=85)
    else:
        image.save(path, "PNG", optimize=True)
    print("wrote", path)


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    write("application-form.pdf", "A4", """
      <div class="page"><h1>Application Form</h1>
        <h2>1. Applicant</h2>
        <table><tr><th>Name</th><td>Alex Example</td></tr>
               <tr><th>Date of birth</th><td>1 January 1990</td></tr>
               <tr><th>Address</th><td>1 Sample Street, 12345 Example City</td></tr></table>
        <h2>2. Programme</h2>
        <div class="box">Master of Science in Example Studies, starting winter term.</div>
        <p>Programme details: <a href="https://example.org/programme">example.org/programme</a></p>
      </div>
      <div class="page"><h1>Application Form (continued)</h1>
        <h2>3. Declaration</h2>
        <div class="box">I confirm that the information given is complete and correct.</div>
        <p>Signature: ____________________ Date: ____________</p>
      </div>""")
    write("passport.pdf", "A4", """
      <h1>Passport Copy</h1>
      <div class="box" style="height: 85mm">Photo page of the passport (placeholder)</div>
      <p>Certified true copy.</p>""")
    write("diploma.pdf", "A4 landscape", """
      <div style="text-align:center; padding-top: 25mm">
        <h1 style="font-size: 28pt">Diploma</h1>
        <p>This certifies that <b>Alex Example</b> has completed the degree of</p>
        <p style="font-size: 16pt; margin: 8mm 0">Bachelor of Arts in Example Studies</p>
        <p>Example University, 2024</p></div>""")
    rows = "".join(f"<tr><td>EX-{100 + i}</td><td>Example course {i}</td><td>6</td>"
                   f"<td>{1 + (i % 3)}.{i % 10}</td></tr>" for i in range(1, 70))
    write("transcript.pdf", "letter", f"""
      <h1>Academic Transcript</h1>
      <table><tr><th>Code</th><th>Course</th><th>Credits</th><th>Grade</th></tr>{rows}</table>""")

    # Photos and scans, as a phone or scanner would produce them.
    card = (1012, 638)  # ID-1 card proportions
    write_image("id-card-front.jpg", card, "IDENTITY CARD",
                ["Surname: EXAMPLE", "Given names: ALEX", "Date of birth: 01.01.1990"])
    write_image("id-card-back.jpg", card, "IDENTITY CARD",
                ["Address: 1 Sample Street", "12345 Example City", "Valid until: 31.12.2034"])
    page = (1240, 1754)  # A4 at 150 dpi
    write_image("certificates/language.png", page, "Language Certificate",
                ["English, level C1", "Example Language Institute", "Issued 2023"])
    write_image("certificates/first-aid.png", page, "First Aid Course",
                ["Completed 16 hours", "Example Red Cross", "Issued 2022"])
    write_image("certificates/internship.png", page, "Internship Reference",
                ["Example Company Ltd.", "Six months, full time", "Issued 2023"])
    write_image("certificates/award.png", (1754, 1240), "Student Award",
                ["Best Thesis in Example Studies", "Example University", "Awarded 2024"])


if __name__ == "__main__":
    main()
