"""Metadata extraction and management service"""
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from mutagen import File
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON
from mutagen.mp3 import MP3
import re

logger = logging.getLogger(__name__)


class MetadataService:
    """Service for extracting and managing audio metadata"""
    
    def __init__(self):
        self.supported_formats = ['.flac', '.mp3', '.m4a', '.opus']
    
    def extract_metadata(self, file_path: Path) -> Dict[str, Any]:
        """
        Extract metadata from audio file
        
        Returns:
            Dictionary with metadata (artist, album, title, year, genre, duration)
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            audio_file = File(str(file_path))
            
            if audio_file is None:
                # If metadata extraction fails, return basic info from filename
                return {
                    "artist": "Unknown Artist",
                    "album": None,
                    "title": file_path.stem,
                    "year": None,
                    "genre": None,
                    "duration": None,
                    "file_size": file_path.stat().st_size
                }
            
            metadata = {
                "artist": self._get_tag(audio_file, ["artist", "TPE1", "©ART"]),
                "album": self._get_tag(audio_file, ["album", "TALB", "©alb"]),
                "title": self._get_tag(audio_file, ["title", "TIT2", "©nam"]),
                "year": self._extract_year(audio_file),
                "genre": self._get_tag(audio_file, ["genre", "TCON", "©gen"]),
                "duration": int(audio_file.info.length) if hasattr(audio_file.info, 'length') else None,
                "file_size": file_path.stat().st_size
            }
            
            return metadata
            
        except Exception as e:
            error_msg = str(e) if str(e) else "Unknown error"
            logger.warning(f"Failed to extract metadata from {file_path}: {error_msg}")
            # Return basic metadata if extraction fails
            return {
                "artist": "Unknown Artist",
                "album": None,
                "title": file_path.stem,
                "year": None,
                "genre": None,
                "duration": None,
                "file_size": file_path.stat().st_size
            }
    
    def update_metadata(
        self,
        file_path: Path,
        artist: Optional[str] = None,
        album: Optional[str] = None,
        title: Optional[str] = None,
        year: Optional[int] = None,
        genre: Optional[str] = None
    ) -> bool:
        """
        Update metadata in audio file
        
        Returns:
            True if successful
        """
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        try:
            audio_file = File(str(file_path))
            
            if audio_file is None:
                raise ValueError(f"Unsupported file format: {file_path.suffix}")
            
            # Update tags based on file type
            if isinstance(audio_file, FLAC):
                if artist:
                    audio_file["ARTIST"] = [artist]
                    logger.debug(f"Set ARTIST: {artist}")
                if album:
                    audio_file["ALBUM"] = [album]
                    logger.debug(f"Set ALBUM: {album}")
                if title:
                    audio_file["TITLE"] = [title]
                    logger.debug(f"Set TITLE: {title}")
                if year:
                    audio_file["DATE"] = [str(year)]
                    logger.debug(f"Set DATE: {year}")
                if genre:
                    audio_file["GENRE"] = [genre]
                    logger.debug(f"Set GENRE: {genre}")
            
            elif isinstance(audio_file, MP3):
                if not audio_file.tags:
                    audio_file.add_tags()
                
                if artist:
                    audio_file.tags["TPE1"] = TPE1(encoding=3, text=artist)
                if album:
                    audio_file.tags["TALB"] = TALB(encoding=3, text=album)
                if title:
                    audio_file.tags["TIT2"] = TIT2(encoding=3, text=title)
                if year:
                    audio_file.tags["TDRC"] = TDRC(encoding=3, text=str(year))
                if genre:
                    audio_file.tags["TCON"] = TCON(encoding=3, text=genre)
            
            else:
                # For other formats, try generic tags
                if artist:
                    audio_file["artist"] = artist
                if album:
                    audio_file["album"] = album
                if title:
                    audio_file["title"] = title
                if year:
                    audio_file["date"] = str(year)
                if genre:
                    audio_file["genre"] = genre
            
            audio_file.save()
            return True
            
        except Exception as e:
            raise Exception(f"Failed to update metadata: {str(e)}")
    
    def normalize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize metadata values (clean, trim, etc.)
        
        Returns:
            Normalized metadata dictionary
        """
        normalized = {}
        
        for key, value in metadata.items():
            if value is None:
                normalized[key] = None
            elif isinstance(value, str):
                # Clean and normalize string values
                normalized[key] = self._clean_string(value)
            elif isinstance(value, list) and len(value) > 0:
                # Take first value from list
                normalized[key] = self._clean_string(str(value[0]))
            else:
                normalized[key] = value
        
        return normalized
    
    def _get_tag(self, audio_file: Any, tag_names: list) -> Optional[str]:
        """Get tag value from audio file, trying multiple tag names"""
        for tag_name in tag_names:
            try:
                if hasattr(audio_file, 'get'):
                    value = audio_file.get(tag_name)
                elif hasattr(audio_file, 'tags') and audio_file.tags:
                    value = audio_file.tags.get(tag_name)
                else:
                    continue
                
                if value:
                    if isinstance(value, list):
                        return str(value[0]) if value else None
                    return str(value)
            except (KeyError, AttributeError):
                continue
        
        return None
    
    def _extract_year(self, audio_file: Any) -> Optional[int]:
        """Extract year from date tag"""
        date_tags = ["date", "TDRC", "DATE", "©day"]
        
        for tag_name in date_tags:
            try:
                value = self._get_tag(audio_file, [tag_name])
                if value:
                    # Extract year from date string (e.g., "2023", "2023-01-01")
                    year_match = re.search(r'\d{4}', str(value))
                    if year_match:
                        return int(year_match.group())
            except (ValueError, AttributeError):
                continue
        
        return None
    
    def _clean_string(self, value: str) -> str:
        """Clean and normalize string value"""
        if not value:
            return ""
        
        # Remove extra whitespace
        cleaned = re.sub(r'\s+', ' ', str(value).strip())
        
        # Remove null bytes
        cleaned = cleaned.replace('\x00', '')
        
        return cleaned

