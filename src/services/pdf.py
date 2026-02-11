"""PDF generation service — create PDF from transcription + analysis."""

import logging
import os
import tempfile
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# Try to register a Cyrillic-capable font
_FONT_REGISTERED = False
_FONT_NAME = "Helvetica"  # fallback


def _register_cyrillic_font() -> str:
    """Try to register DejaVu Sans for Cyrillic support."""
    global _FONT_REGISTERED, _FONT_NAME

    if _FONT_REGISTERED:
        return _FONT_NAME

    # Common paths for DejaVu Sans
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            try:
                pdfmetrics.registerFont(TTFont("DejaVuSans", path))
                _FONT_NAME = "DejaVuSans"
                _FONT_REGISTERED = True
                logger.info("Registered Cyrillic font from %s", path)
                return _FONT_NAME
            except Exception as e:
                logger.warning("Failed to register font %s: %s", path, e)

    logger.warning("No Cyrillic font found, using Helvetica (may not render correctly)")
    _FONT_REGISTERED = True
    return _FONT_NAME


class PDFGenerator:
    """Generates PDF documents from transcription results."""

    def __init__(self, output_dir: str = "/tmp/transcribe") -> None:
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def generate(
        self,
        file_name: str,
        transcription_text: str,
        analysis_text: str,
        created_at: datetime | None = None,
    ) -> str:
        """Generate a PDF document with transcription and analysis.

        Args:
            file_name: Original file name.
            transcription_text: Full transcription text.
            analysis_text: Analysis and recommendations text.
            created_at: Timestamp of the transcription.

        Returns:
            Path to the generated PDF file.
        """
        font_name = _register_cyrillic_font()
        date_str = (created_at or datetime.now()).strftime("%d.%m.%Y %H:%M")
        safe_name = "".join(c for c in file_name if c.isalnum() or c in ".-_ ")[:50]

        pdf_path = os.path.join(
            self._output_dir,
            f"transcription_{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
        )

        doc = SimpleDocTemplate(
            pdf_path,
            pagesize=A4,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
        )

        styles = getSampleStyleSheet()

        # Custom styles
        title_style = ParagraphStyle(
            "CustomTitle",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=18,
            spaceAfter=12,
        )
        heading_style = ParagraphStyle(
            "CustomHeading",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=14,
            spaceBefore=16,
            spaceAfter=8,
            textColor=colors.HexColor("#333333"),
        )
        body_style = ParagraphStyle(
            "CustomBody",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=10,
            leading=14,
            spaceAfter=6,
        )
        meta_style = ParagraphStyle(
            "Meta",
            parent=styles["Normal"],
            fontName=font_name,
            fontSize=9,
            textColor=colors.grey,
            spaceAfter=4,
        )

        # Build content
        elements = []

        # Title
        elements.append(Paragraph("Транскрибация", title_style))
        elements.append(Spacer(1, 6))

        # Metadata table
        meta_data = [
            ["Файл:", file_name],
            ["Дата:", date_str],
        ]
        meta_table = Table(meta_data, colWidths=[3 * cm, 12 * cm])
        meta_table.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, -1), font_name),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (0, -1), colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 16))

        # Transcription section
        if transcription_text:
            elements.append(Paragraph("Транскрибация", heading_style))
            # Split long text into paragraphs
            for paragraph in transcription_text.split("\n"):
                if paragraph.strip():
                    # Escape XML special chars
                    safe_text = (
                        paragraph.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    elements.append(Paragraph(safe_text, body_style))
            elements.append(Spacer(1, 12))

        # Analysis section
        if analysis_text:
            elements.append(Paragraph("Анализ и план развития", heading_style))
            for paragraph in analysis_text.split("\n"):
                if paragraph.strip():
                    safe_text = (
                        paragraph.replace("&", "&amp;")
                        .replace("<", "&lt;")
                        .replace(">", "&gt;")
                    )
                    # Basic markdown heading support
                    if paragraph.startswith("## "):
                        elements.append(Paragraph(safe_text[3:], heading_style))
                    else:
                        elements.append(Paragraph(safe_text, body_style))

        # Build PDF
        doc.build(elements)
        logger.info("Generated PDF: %s", pdf_path)
        return pdf_path
