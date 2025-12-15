"""Spotify downloader (placeholder)"""
import logging
from pathlib import Path
from typing import Optional, Tuple
from app.services.downloader.base import BaseDownloader

logger = logging.getLogger(__name__)


class SpotifyDownloader(BaseDownloader):
    """Downloader for Spotify (not yet implemented)"""
    
    def download(self, url: str) -> Tuple[Optional[Path], dict]:
        """
        Download audio from Spotify
        
        Returns:
            Tuple of (file_path, metadata_dict)
        """
        raise NotImplementedError("Spotify downloader is not yet implemented")
    
    def extract_metadata(self, url: str) -> dict:
        """
        Extract metadata from Spotify URL
        
        Returns:
            Dictionary with metadata
        """
        logger.warning("Spotify metadata extraction is not yet implemented")
        return {}
