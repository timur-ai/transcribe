"""Unit tests for PDF generation service."""

import os
from datetime import datetime

import pytest

from src.services.pdf import PDFGenerator


@pytest.fixture
def pdf_gen(tmp_path):
    return PDFGenerator(output_dir=str(tmp_path))


class TestPDFGenerator:
    def test_generates_pdf_file(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="test.mp3",
            transcription_text="Hello world. This is a test.",
            analysis_text="## Summary\nTest analysis.",
            created_at=datetime(2025, 1, 15, 12, 30),
        )
        assert os.path.exists(path)
        assert path.endswith(".pdf")
        assert os.path.getsize(path) > 0

    def test_empty_transcription(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="empty.ogg",
            transcription_text="",
            analysis_text="No analysis possible.",
        )
        assert os.path.exists(path)

    def test_empty_analysis(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="no_analysis.ogg",
            transcription_text="Some transcription text.",
            analysis_text="",
        )
        assert os.path.exists(path)

    def test_cyrillic_text(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="russian.ogg",
            transcription_text="Привет мир. Это тестовая транскрибация на русском языке.",
            analysis_text="## Краткое резюме\nТестовый анализ с кириллицей.",
        )
        assert os.path.exists(path)
        assert os.path.getsize(path) > 100

    def test_long_text(self, pdf_gen):
        long_text = "Это длинный текст для тестирования. " * 500
        path = pdf_gen.generate(
            file_name="long.ogg",
            transcription_text=long_text,
            analysis_text="## Резюме\n" + long_text[:1000],
        )
        assert os.path.exists(path)

    def test_special_characters(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="special <chars> & \"quotes\".ogg",
            transcription_text="Text with <tags> & special \"chars\"",
            analysis_text="Analysis with 100% & <html>",
        )
        assert os.path.exists(path)

    def test_no_created_at(self, pdf_gen):
        path = pdf_gen.generate(
            file_name="test.ogg",
            transcription_text="Some text",
            analysis_text="Some analysis",
            created_at=None,
        )
        assert os.path.exists(path)
