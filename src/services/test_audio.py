"""Unit tests for audio processing service."""

import json

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.audio import AudioProcessor, AudioProcessingError


@pytest.fixture
def processor():
    return AudioProcessor()


class TestIsVideo:
    def test_mp4(self):
        assert AudioProcessor.is_video("file.mp4") is True

    def test_avi(self):
        assert AudioProcessor.is_video("file.AVI") is True

    def test_mov(self):
        assert AudioProcessor.is_video("/path/to/file.mov") is True

    def test_mkv(self):
        assert AudioProcessor.is_video("file.mkv") is True

    def test_webm(self):
        assert AudioProcessor.is_video("file.webm") is True

    def test_not_video(self):
        assert AudioProcessor.is_video("file.mp3") is False
        assert AudioProcessor.is_video("file.ogg") is False
        assert AudioProcessor.is_video("file.txt") is False


class TestIsAudio:
    def test_ogg(self):
        assert AudioProcessor.is_audio("file.ogg") is True

    def test_mp3(self):
        assert AudioProcessor.is_audio("file.MP3") is True

    def test_wav(self):
        assert AudioProcessor.is_audio("file.wav") is True

    def test_flac(self):
        assert AudioProcessor.is_audio("file.flac") is True

    def test_m4a(self):
        assert AudioProcessor.is_audio("file.m4a") is True

    def test_not_audio(self):
        assert AudioProcessor.is_audio("file.mp4") is False
        assert AudioProcessor.is_audio("file.txt") is False


class TestIsSupported:
    def test_all_audio_formats(self):
        for ext in [".ogg", ".mp3", ".wav", ".flac", ".m4a"]:
            assert AudioProcessor.is_supported(f"file{ext}") is True

    def test_all_video_formats(self):
        for ext in [".mp4", ".avi", ".mov", ".mkv", ".webm"]:
            assert AudioProcessor.is_supported(f"file{ext}") is True

    def test_unsupported(self):
        assert AudioProcessor.is_supported("file.txt") is False
        assert AudioProcessor.is_supported("file.pdf") is False
        assert AudioProcessor.is_supported("file.doc") is False


class TestGetDuration:
    async def test_returns_duration(self, processor):
        probe_output = json.dumps({"format": {"duration": "120.5"}})

        with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = probe_output
            duration = await processor.get_duration("file.ogg")

        assert duration == 120.5

    async def test_invalid_output_raises(self, processor):
        with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = "not json"
            with pytest.raises(AudioProcessingError, match="Could not determine"):
                await processor.get_duration("file.ogg")


class TestExtractAudio:
    async def test_calls_ffmpeg(self, processor):
        with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = ""
            result = await processor.extract_audio("input.mp4", "output.ogg")

        assert result == "output.ogg"
        mock_ff.assert_called_once()
        args = mock_ff.call_args[0]
        assert "ffmpeg" in args
        assert "-vn" in args
        assert "libopus" in args


class TestConvertToOgg:
    async def test_calls_ffmpeg(self, processor):
        with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock) as mock_ff:
            mock_ff.return_value = ""
            result = await processor.convert_to_ogg("input.mp3", "output.ogg")

        assert result == "output.ogg"
        mock_ff.assert_called_once()
        args = mock_ff.call_args[0]
        assert "libopus" in args
        assert "48000" in args


class TestSplitFile:
    async def test_no_split_needed(self, processor):
        with patch.object(processor, "get_duration", new_callable=AsyncMock) as mock_dur:
            mock_dur.return_value = 600.0  # 10 minutes
            with patch.object(processor, "get_file_size", return_value=50_000_000):
                result = await processor.split_file("file.ogg", "/tmp/parts")

        assert result == ["file.ogg"]

    async def test_split_by_duration(self, processor, tmp_path):
        parts_dir = str(tmp_path / "parts")

        # Create fake output files to simulate ffmpeg output
        import os
        os.makedirs(parts_dir, exist_ok=True)
        for i in range(3):
            (tmp_path / "parts" / f"file_part_{i:03d}.ogg").write_bytes(b"fake")

        with patch.object(processor, "get_duration", new_callable=AsyncMock) as mock_dur:
            mock_dur.return_value = 50000.0  # > 14400
            with patch.object(processor, "get_file_size", return_value=100_000):
                with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock):
                    result = await processor.split_file("file.ogg", parts_dir)

        assert len(result) == 3

    async def test_split_by_size(self, processor, tmp_path):
        parts_dir = str(tmp_path / "parts")

        import os
        os.makedirs(parts_dir, exist_ok=True)
        for i in range(2):
            (tmp_path / "parts" / f"file_part_{i:03d}.ogg").write_bytes(b"fake")

        with patch.object(processor, "get_duration", new_callable=AsyncMock) as mock_dur:
            mock_dur.return_value = 3600.0  # 1 hour, within duration limit
            with patch.object(processor, "get_file_size", return_value=2_000_000_000):  # > 1GB
                with patch.object(processor, "_run_ffmpeg", new_callable=AsyncMock):
                    result = await processor.split_file("file.ogg", parts_dir)

        assert len(result) == 2


class TestRunFfmpeg:
    async def test_ffmpeg_error(self, processor):
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"", b"error message")
        mock_process.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            with pytest.raises(AudioProcessingError, match="FFmpeg command failed"):
                await processor._run_ffmpeg("ffmpeg", "-i", "bad.ogg")

    async def test_ffmpeg_success(self, processor):
        mock_process = AsyncMock()
        mock_process.communicate.return_value = (b"output data", b"")
        mock_process.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            result = await processor._run_ffmpeg("ffmpeg", "-version")

        assert result == "output data"
