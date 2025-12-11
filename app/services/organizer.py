"""File organization service for Plex-compatible structure"""
from pathlib import Path
from typing import Optional, Dict, Any
import re
import shutil
import logging
from app.config import settings
from app.services.metadata import MetadataService

logger = logging.getLogger(__name__)


class OrganizerService:
    """Service for organizing files in Plex-compatible structure"""
    
    def __init__(self):
        self.music_dir = settings.MUSIC_DIR
        self.metadata_service = MetadataService()
        self.include_year = settings.INCLUDE_YEAR_IN_ALBUM
    
    def organize_file(
        self,
        source_file: Path,
        metadata: Optional[Dict[str, Any]] = None,
        track_number: Optional[int] = None
    ) -> Path:
        """
        Organize file in Plex structure: Artist/Album (Year)/Track - Title.flac
        
        Args:
            source_file: Source file path
            metadata: Optional metadata dict (will be extracted if not provided)
            track_number: Optional track number
        
        Returns:
            Final destination path
        """
        if not source_file.exists():
            raise FileNotFoundError(f"Source file not found: {source_file}")
        
        # Extract metadata if not provided
        if metadata is None:
            metadata = self.metadata_service.extract_metadata(source_file)
        
        # Normalize metadata
        metadata = self.metadata_service.normalize_metadata(metadata)
        
        # Get required fields
        artist = metadata.get("artist") or "Unknown Artist"
        album = metadata.get("album") or "Unknown Album"
        title = metadata.get("title") or source_file.stem
        year = metadata.get("year")
        
        # Extract main artist (before comma or "feat") for folder structure
        # This prevents creating multiple folders for the same artist with different collaborations
        main_artist = self._extract_main_artist(artist)
        
        # Clean names for filesystem
        artist_clean = self._clean_filename(main_artist)  # Use main artist for folder
        album_clean = self._clean_filename(album)
        title_clean = self._clean_filename(title)
        
        # Build directory structure
        if self.include_year and year:
            album_dir_name = f"{album_clean} ({year})"
        else:
            album_dir_name = album_clean
        
        # Create destination directory
        dest_dir = self.music_dir / artist_clean / album_dir_name
        dest_dir.mkdir(parents=True, exist_ok=True)
        
        # Build filename
        if track_number is not None:
            filename = f"{track_number:02d} - {title_clean}{source_file.suffix}"
        else:
            filename = f"{title_clean}{source_file.suffix}"
        
        dest_path = dest_dir / filename
        
        # Move file (rename if same filesystem, copy+delete otherwise)
        logger.info(f"Organizing file: {source_file} -> {dest_path}")
        logger.info(f"Source dir: {source_file.parent}, Dest dir: {dest_dir}")
        
        if source_file.parent == dest_dir:
            # Already in destination, just rename if needed
            logger.info(f"File already in destination directory, renaming if needed")
            if source_file.name != filename:
                source_file.rename(dest_path)
        else:
            # Move to destination (from downloads to music)
            logger.info(f"Moving file from downloads to music directory: {source_file} -> {dest_path}")
            try:
                shutil.move(str(source_file), str(dest_path))
                logger.info(f"File successfully moved to: {dest_path}")
                
                # Verify the file was moved
                if not dest_path.exists():
                    raise FileNotFoundError(f"File move failed: {dest_path} does not exist after move")
                if source_file.exists():
                    logger.warning(f"Source file still exists after move: {source_file}")
                    # Try to remove it
                    try:
                        source_file.unlink()
                        logger.info(f"Removed leftover source file: {source_file}")
                    except Exception as e:
                        logger.error(f"Failed to remove leftover source file: {e}")
            except Exception as e:
                logger.error(f"Failed to move file: {e}")
                raise
        
        # Update metadata in file (force update to ensure all tags are set)
        try:
            # Ensure album is set
            if not album:
                album = "Unknown Album"
                logger.warning(f"Album not provided, using 'Unknown Album' for {dest_path.name}")
            
            self.metadata_service.update_metadata(
                dest_path,
                artist=artist,
                album=album,
                title=title,
                year=year,
                genre=metadata.get("genre")
            )
            logger.info(f"✅ Metadata updated in file: artist={artist}, title={title}, album={album}")
            
            # Verify metadata was written
            if dest_path.suffix.lower() == ".flac":
                from mutagen.flac import FLAC
                flac_file = FLAC(str(dest_path))
                written_album = flac_file.get("ALBUM", [None])[0] if flac_file.get("ALBUM") else None
                if written_album != album:
                    logger.warning(f"Album mismatch! Expected: {album}, Written: {written_album}")
                else:
                    logger.info(f"✅ Verified: Album '{album}' written to FLAC file")
        except Exception as e:
            logger.warning(f"Failed to update metadata in file: {e}")
            logger.exception("Full traceback:")
            # Continue anyway, file is still organized
        
        return dest_path
    
    def _extract_main_artist(self, artist: str) -> str:
        """
        Extract main artist name (before comma or 'feat'/'ft'/'featuring')
        This prevents creating multiple folders for the same artist with different collaborations
        
        Examples:
        - "Mister You, Bimbim" -> "Mister You"
        - "Paul Kalkbrenner, Stromae" -> "Paul Kalkbrenner"
        - "Artist feat. Other" -> "Artist"
        """
        if not artist:
            return "Unknown Artist"
        
        # Remove common collaboration markers
        artist = artist.strip()
        
        # Split by comma and take first part
        if ',' in artist:
            main_artist = artist.split(',')[0].strip()
        # Check for feat/ft/featuring
        elif ' feat. ' in artist.lower() or ' feat ' in artist.lower():
            main_artist = artist.split(' feat. ')[0].split(' feat ')[0].strip()
        elif ' ft. ' in artist.lower() or ' ft ' in artist.lower():
            main_artist = artist.split(' ft. ')[0].split(' ft ')[0].strip()
        elif ' featuring ' in artist.lower():
            main_artist = artist.split(' featuring ')[0].strip()
        else:
            # No collaboration marker, use full name
            main_artist = artist
        
        return main_artist if main_artist else "Unknown Artist"
    
    def _clean_filename(self, name: str) -> str:
        """
        Clean filename to be filesystem-safe and Plex-compatible
        
        Removes or replaces invalid characters
        """
        if not name:
            return "Unknown"
        
        # Remove invalid characters for filesystem
        # Windows: < > : " / \ | ? *
        # Unix: /
        invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
        cleaned = re.sub(invalid_chars, '', name)
        
        # Remove leading/trailing dots and spaces (Windows issue)
        cleaned = cleaned.strip('. ')
        
        # Replace multiple spaces with single space
        cleaned = re.sub(r'\s+', ' ', cleaned)
        
        # Limit length (filesystem limit, typically 255)
        if len(cleaned) > 200:
            cleaned = cleaned[:200]
        
        # Ensure not empty
        if not cleaned:
            return "Unknown"
        
        return cleaned
    
    def get_plex_structure(self, file_path: Path) -> Dict[str, str]:
        """
        Get Plex structure information from file path
        
        Returns:
            Dictionary with artist, album, title extracted from path
        """
        try:
            # Path format: music/Artist/Album (Year)/Track - Title.flac
            parts = file_path.relative_to(self.music_dir).parts
            
            if len(parts) >= 2:
                artist = parts[0]
                album_with_year = parts[1]
                
                # Extract year from album name if present
                year_match = re.search(r'\((\d{4})\)', album_with_year)
                year = year_match.group(1) if year_match else None
                album = re.sub(r'\s*\(\d{4}\)\s*', '', album_with_year)
                
                # Extract track number and title from filename
                filename = parts[-1] if len(parts) > 2 else file_path.name
                track_match = re.match(r'(\d+)\s*-\s*(.+)', filename)
                if track_match:
                    track_number = track_match.group(1)
                    title = track_match.group(2).rsplit('.', 1)[0]
                else:
                    track_number = None
                    title = filename.rsplit('.', 1)[0]
                
                return {
                    "artist": artist,
                    "album": album,
                    "year": year,
                    "track_number": track_number,
                    "title": title
                }
        except Exception:
            pass
        
        return {}

