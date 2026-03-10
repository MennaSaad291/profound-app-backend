import io
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

# -----------------------------
# THEMES CONFIGURATION
# -----------------------------
THEMES = {
    "Modern Minimalist": {
        "bg": "backgrounds/modern.jpg",
        "text": "F8FAFC", # Light text for dark backgrounds
        "accent": "38BDF8", # Sky blue accent
        "secondary": "E5E7EB"
    },
    "Dark Mode Tech": {
        "bg": "backgrounds/dark.jpg",
        "text": "F8FAFC",
        "accent": "38BDF8",
        "secondary": "1E293B"
    },
    "Classic Academic": {
        "bg": "backgrounds/academic.png",
        "text": "1E1E1E",
        "accent": "800000",
        "secondary": "E5E7EB"
    },
    "Vibrant Creative": {
        "bg": "backgrounds/creative.png",
        "text": "431407",
        "accent": "F97316",
        "secondary": "FED7AA"
    }
}

def apply_background(slide, bg):
    if bg and os.path.exists(bg):
        slide.shapes.add_picture(bg, 0, 0, width=Inches(13.333), height=Inches(7.5))

def apply_theme_design(slide, theme_name, colors):
    # Optional overlays if images are missing or for extra flare
    if theme_name == "Modern Minimalist":
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(0.1), Inches(7.5))
        bar.fill.solid()
        bar.fill.fore_color.rgb = RGBColor.from_string(colors["accent"])
        bar.line.fill.background()

def create_pptx(data: dict):
    theme_name = data.get("theme", "Modern Minimalist")
    colors = THEMES.get(theme_name, THEMES["Modern Minimalist"])
    
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)

    slides = data.get("slides", [])

    for index, slide_data in enumerate(slides):
        slide = prs.slides.add_slide(prs.slide_layouts[6]) # Blank Layout
        apply_background(slide, colors["bg"])
        apply_theme_design(slide, theme_name, colors)

        is_title_slide = (index == 0)

        # -----------------------------
        # TITLE BOX (Structured Header)
        # -----------------------------
        # Positioned to avoid overlapping left-side graphics
        title_top = Inches(2.0) if is_title_slide else Inches(0.6)
        title_left = Inches(1.0)
        title_width = Inches(11.3)
        
        title_box = slide.shapes.add_textbox(title_left, title_top, title_width, Inches(1.2))
        title_tf = title_box.text_frame
        title_tf.word_wrap = True # CRITICAL: Prevents horizontal overflow
        
        title_p = title_tf.paragraphs[0]
        title_p.text = str(slide_data.get("title", "No Title")).strip()
        title_p.font.size = Pt(54) if is_title_slide else Pt(44)
        title_p.font.bold = True
        title_p.font.color.rgb = RGBColor.from_string(colors["accent"])
        
        if is_title_slide:
            title_p.alignment = PP_ALIGN.CENTER

        # -----------------------------
        # CONTENT BOX (Bullet Points)
        # -----------------------------
        if not is_title_slide:
            # Constraints: Start below title, stay within slide margins
            body_box = slide.shapes.add_textbox(
                Inches(1.0),   # Left margin
                Inches(2.2),   # Top (below title)
                Inches(11.0),  # Wider width to use slide space
                Inches(4.5)    # Height limit
            )
            body_tf = body_box.text_frame
            body_tf.word_wrap = True # CRITICAL: Forces text to wrap at boundary
            body_tf.clear()

            content_data = slide_data.get("content", [])
            
            # Ensure content is a list of strings
            if isinstance(content_data, str):
                bullets = [content_data]
            else:
                bullets = content_data

            for i, bullet_text in enumerate(bullets):
                p = body_tf.add_paragraph() if i > 0 else body_tf.paragraphs[0]
                p.text = str(bullet_text).strip()
                p.font.size = Pt(26)
                p.font.color.rgb = RGBColor.from_string(colors["text"])
                p.level = 0
                p.space_before = Pt(12) # Adds breathing room between bullets
                
                # Apply Bullet Point formatting
                p.alignment = PP_ALIGN.LEFT

        # -----------------------------
        # SPEAKER NOTES
        # -----------------------------
        notes = slide_data.get("speaker_notes")
        if notes:
            slide.notes_slide.notes_text_frame.text = str(notes)

    stream = io.BytesIO()
    prs.save(stream)
    stream.seek(0)
    return stream