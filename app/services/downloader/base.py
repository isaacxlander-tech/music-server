"""Base downloader class for platform-specific downloaders"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple
from app.models.track import SourceType


class BaseDownloader(ABC):
    """Abstract base class for platform-specific downloaders"""
    
    @abstractmethod
    def download(self, url: str) -> Tuple[Optional[Path], dict]:
        """
        Download audio from URL
        
        Args:
            url: URL to download from
            
        Returns:
            Tuple of (file_path, metadata_dict)
        """
        pass
    
    @abstractmethod
    def extract_metadata(self, url: str) -> dict:
        """
        Extract metadata from URL before downloading
        
        Args:
            url: URL to extract metadata from
            
        Returns:
            Dictionary with metadata (title, artist, album, thumbnail, etc.)
        """
        pass
    
    def detect_source(self, url: str) -> SourceType:
        """
        Detect the source type from URL
        
        Args:
            url: URL to analyze
            
        Returns:
            SourceType enum value
        """
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower or "music.youtube.com" in url_lower:
            return SourceType.YOUTUBE
        elif "spotify.com" in url_lower or "open.spotify.com" in url_lower:
            return SourceType.SPOTIFY
        elif "soundcloud.com" in url_lower:
            return SourceType.SOUNDCLOUD
        return SourceType.UNKNOWN
