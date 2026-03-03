import io
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_AUTO_SIZE
from pptx.enum.shapes import MSO_SHAPE

THEMES = {
    "Modern Minimalist": {"bg": "FFFFFF", "text": "0F172A", "accent": "9333EA"},
    "Dark Mode Tech": {"bg": "1E293B", "text": "FFFFFF", "accent": "38BDF8"},
}

def create_pptx(data: dict):
    theme_name = data.get('theme', 'Modern Minimalist')
    colors = THEMES.get(theme_name, THEMES['Modern Minimalist'])
    
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)

    for slide_data in data.get('slides', []):
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = RGBColor.from_string(colors['bg'])

        # Accent Circle
        circle = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(10.5), Inches(-0.5), Inches(3), Inches(3))
        circle.fill.solid()
        circle.fill.fore_color.rgb = RGBColor.from_string(colors['accent'])
        circle.line.fill.background()

        # Content
        title = slide.shapes.add_textbox(Inches(0.5), Inches(0.5), Inches(10), Inches(1))
        title.text_frame.paragraphs[0].text = slide_data.get("title", "")
        title.text_frame.paragraphs[0].font.size = Pt(40)
        title.text_frame.paragraphs[0].font.color.rgb = RGBColor.from_string(colors['accent'])

    stream = io.BytesIO()
    prs.save(stream)
    stream.seek(0)
    return stream