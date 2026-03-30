from docx import Document
import PyPDF2

def extract_text(file_path):
    text = ""
    try:
        if file_path.endswith(".txt"):
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()

        elif file_path.endswith(".docx"):
            doc = Document(file_path)
            text = "\n".join([p.text for p in doc.paragraphs])

        elif file_path.endswith(".pdf"):
            reader = PyPDF2.PdfReader(file_path)
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"

        return text.replace('\x00', '').strip()

    except Exception as e:
        print(f"Error extracting text: {e}")
        return ""