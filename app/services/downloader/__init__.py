"""Download service for various music platforms"""
import logging
from pathlib import Path
from typing import Optional, Tuple
from app.config import settings
from app.models.track import SourceType
from app.services.downloader.base import BaseDownloader
from app.services.downloader.youtube import YouTubeDownloader
from app.services.downloader.spotify import SpotifyDownloader
from app.services.downloader.soundcloud import SoundCloudDownloader
from app.services.downloader.utils import convert_to_flac_with_thumbnail

logger = logging.getLogger(__name__)


class DownloaderService:
    """Service for downloading music from various sources (router using Strategy pattern)"""
    
    def __init__(self):
        self.downloads_dir = settings.DOWNLOADS_DIR
        self.audio_format = settings.AUDIO_FORMAT
        self.audio_quality = settings.AUDIO_QUALITY
        
        # Initialize platform-specific downloaders
        self.downloaders: dict[SourceType, BaseDownloader] = {
            SourceType.YOUTUBE: YouTubeDownloader(),
            SourceType.SPOTIFY: SpotifyDownloader(),
            SourceType.SOUNDCLOUD: SoundCloudDownloader(),
        }
    
    def detect_source(self, url: str) -> SourceType:
        """Detect the source type from URL"""
        # Use the base downloader's detect_source method
        return self.downloaders[SourceType.YOUTUBE].detect_source(url)
    
    def download(self, url: str, source: Optional[SourceType] = None) -> Tuple[Optional[Path], dict, SourceType]:
        """
        Download audio from URL (auto-detect source if not provided)
        
        Returns:
            Tuple of (file_path, metadata_dict, source_type)
        """
        if source is None:
            source = self.detect_source(url)
        
        # Convert to SourceType if it's an integer or string (from database)
        if isinstance(source, (int, str)):
            try:
                if isinstance(source, int):
                    source = SourceType(source)
                else:
                    source = SourceType[source.upper()]
            except (ValueError, KeyError):
                logger.warning(f"Invalid source type: {source}, auto-detecting...")
                source = self.detect_source(url)
        
        # Route to the appropriate downloader
        if source not in self.downloaders:
            raise ValueError(f"Unsupported source type: {source}")
        
        downloader = self.downloaders[source]
        file_path, metadata = downloader.download(url)
        
        return file_path, metadata, source
    
    def convert_to_flac_with_thumbnail(self, m4a_file: Path, thumbnail_url: Optional[str] = None) -> Path:
        """
        Convert m4a file to FLAC and embed thumbnail webp
        (Maintained for backward compatibility with routes.py)
        
        Args:
            m4a_file: Path to m4a file
            thumbnail_url: Optional thumbnail URL
            
        Returns:
            Path to converted FLAC file
        """
        return convert_to_flac_with_thumbnail(m4a_file, thumbnail_url)


# Export for backward compatibility
__all__ = ['DownloaderService']
