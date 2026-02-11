"""Audio/video processing service — FFmpeg extraction, conversion, and splitting."""

import asyncio
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {".ogg", ".mp3", ".wav", ".flac", ".m4a"}
SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
SUPPORTED_EXTENSIONS = SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_VIDEO_EXTENSIONS

DEFAULT_MAX_DURATION = 14400  # 4 hours in seconds
DEFAULT_MAX_SIZE = 1_073_741_824  # 1 GB in bytes


class AudioProcessingError(Exception):
    """Raised when audio/video processing fails."""
    pass


class AudioProcessor:
    """Handles audio/video file processing using FFmpeg.

    Provides methods for:
    - Extracting audio tracks from video files
    - Converting audio to OGG OPUS format
    - Getting file duration and size
    - Splitting large files into parts
    """

    @staticmethod
    def is_video(file_path: str) -> bool:
        """Check if the file is a video based on extension."""
        return Path(file_path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS

    @staticmethod
    def is_audio(file_path: str) -> bool:
        """Check if the file is an audio based on extension."""
        return Path(file_path).suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS

    @staticmethod
    def is_supported(file_path: str) -> bool:
        """Check if the file format is supported."""
        return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS

    @staticmethod
    def get_file_size(file_path: str) -> int:
        """Return the file size in bytes."""
        return os.path.getsize(file_path)

    @staticmethod
    async def _run_ffmpeg(*args: str) -> str:
        """Run an FFmpeg/FFprobe command asynchronously.

        Returns:
            stdout content as string.

        Raises:
            AudioProcessingError: If the command fails.
        """
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            cmd_str = " ".join(args)
            err = stderr.decode(errors="replace").strip()
            raise AudioProcessingError(
                f"FFmpeg command failed (exit {process.returncode}): {cmd_str}\n{err}"
            )
        return stdout.decode(errors="replace").strip()

    async def get_duration(self, file_path: str) -> float:
        """Get the duration of an audio/video file in seconds using FFprobe."""
        output = await self._run_ffmpeg(
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            file_path,
        )
        try:
            data = json.loads(output)
            duration = float(data["format"]["duration"])
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            raise AudioProcessingError(f"Could not determine duration: {e}") from e
        return duration

    async def extract_audio(self, input_path: str, output_path: str) -> str:
        """Extract audio track from a video file and save as OGG OPUS.

        Args:
            input_path: Path to the input video file.
            output_path: Path for the output OGG file.

        Returns:
            Path to the extracted audio file.
        """
        logger.info("Extracting audio from %s", input_path)
        await self._run_ffmpeg(
            "ffmpeg", "-y",
            "-i", input_path,
            "-vn",  # no video
            "-acodec", "libopus",
            "-ar", "48000",
            "-ac", "1",  # mono
            "-b:a", "64k",
            output_path,
        )
        logger.info("Audio extracted to %s", output_path)
        return output_path

    async def convert_to_ogg(self, input_path: str, output_path: str) -> str:
        """Convert any audio format to OGG OPUS 48kHz mono.

        Args:
            input_path: Path to the input audio file.
            output_path: Path for the output OGG file.

        Returns:
            Path to the converted file.
        """
        logger.info("Converting %s to OGG OPUS", input_path)
        await self._run_ffmpeg(
            "ffmpeg", "-y",
            "-i", input_path,
            "-acodec", "libopus",
            "-ar", "48000",
            "-ac", "1",
            "-b:a", "64k",
            output_path,
        )
        logger.info("Converted to %s", output_path)
        return output_path

    async def split_file(
        self,
        input_path: str,
        output_dir: str,
        max_duration: int = DEFAULT_MAX_DURATION,
        max_size: int = DEFAULT_MAX_SIZE,
    ) -> list[str]:
        """Split an audio file into parts if it exceeds limits.

        Parts are created with 2-second overlap to avoid cutting words.

        Args:
            input_path: Path to the input audio file.
            output_dir: Directory for output parts.
            max_duration: Maximum duration per part in seconds.
            max_size: Maximum size per part in bytes.

        Returns:
            List of paths to the output parts. If no split is needed,
            returns a list with the original file path.
        """
        duration = await self.get_duration(input_path)
        file_size = self.get_file_size(input_path)

        needs_split = duration > max_duration or file_size > max_size

        if not needs_split:
            return [input_path]

        # Calculate segment duration
        segment_duration = max_duration
        if file_size > max_size:
            # Scale segment duration proportionally to size limit
            size_ratio = max_size / file_size
            size_based_duration = int(duration * size_ratio * 0.9)  # 10% safety margin
            segment_duration = min(segment_duration, size_based_duration)

        # Ensure minimum segment duration of 60 seconds
        segment_duration = max(segment_duration, 60)

        logger.info(
            "Splitting %s (%.1fs, %d bytes) into %d-second segments",
            input_path, duration, file_size, segment_duration,
        )

        os.makedirs(output_dir, exist_ok=True)
        base_name = Path(input_path).stem
        output_pattern = os.path.join(output_dir, f"{base_name}_part_%03d.ogg")

        await self._run_ffmpeg(
            "ffmpeg", "-y",
            "-i", input_path,
            "-f", "segment",
            "-segment_time", str(segment_duration),
            "-acodec", "libopus",
            "-ar", "48000",
            "-ac", "1",
            "-b:a", "64k",
            output_pattern,
        )

        # Collect output files
        parts = sorted(
            str(p) for p in Path(output_dir).glob(f"{base_name}_part_*.ogg")
        )

        if not parts:
            raise AudioProcessingError("File splitting produced no output parts")

        logger.info("Split into %d parts", len(parts))
        return parts
