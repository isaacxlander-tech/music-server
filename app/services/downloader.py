"""Download service for YouTube and YouTube Music"""
import subprocess
import re
import os
import logging
from pathlib import Path
from typing import Optional, Tuple
from app.config import settings
from app.models.track import SourceType

logger = logging.getLogger(__name__)


class DownloaderService:
    """Service for downloading music from various sources"""
    
    def __init__(self):
        self.downloads_dir = settings.DOWNLOADS_DIR
        self.audio_format = settings.AUDIO_FORMAT
        self.audio_quality = settings.AUDIO_QUALITY
    
    def detect_source(self, url: str) -> SourceType:
        """Detect the source type from URL"""
        url_lower = url.lower()
        if "youtube.com" in url_lower or "youtu.be" in url_lower or "music.youtube.com" in url_lower:
            return SourceType.YOUTUBE
        return SourceType.UNKNOWN
    
    def download_from_youtube(self, url: str) -> Tuple[Optional[Path], dict]:
        """
        Download audio from YouTube using yt-dlp
        
        Returns:
            Tuple of (file_path, metadata_dict)
        """
        try:
            # Check if yt-dlp is available
            try:
                subprocess.run(["yt-dlp", "--version"], capture_output=True, check=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                raise Exception("yt-dlp n'est pas installé ou n'est pas dans le PATH. Installez-le avec: pip install yt-dlp")
            
            # First, extract metadata from URL (artist, thumbnail, etc.)
            metadata = self._extract_metadata_from_url(url)
            
            # Prepare output template
            output_template = str(self.downloads_dir / "%(title)s.%(ext)s")
            
            logger.info(f"Downloading from YouTube: {url}")
            
            # Check for spotdl's ffmpeg if system ffmpeg is not available
            spotdl_dir = Path.home() / ".spotdl"
            ffmpeg_args = []
            if (spotdl_dir / "ffmpeg").exists():
                # Use the full path to ffmpeg executable
                ffmpeg_path = spotdl_dir / "ffmpeg"
                ffmpeg_args = ["--ffmpeg-location", str(ffmpeg_path)]
                logger.info(f"Using ffmpeg from: {ffmpeg_path}")
            else:
                # Try to find ffmpeg in system
                import shutil
                ffmpeg_system = shutil.which("ffmpeg")
                if ffmpeg_system:
                    ffmpeg_args = ["--ffmpeg-location", ffmpeg_system]
                    logger.info(f"Using system ffmpeg from: {ffmpeg_system}")
                else:
                    logger.warning("ffmpeg not found! Audio extraction may fail. Install ffmpeg or ensure spotdl's ffmpeg is available.")
            
            # Build base command - télécharger directement le meilleur format audio (plus rapide)
            # Utilise -x pour extraire l'audio du meilleur format disponible (m4a, opus, mp3)
            # Beaucoup plus rapide que la conversion FLAC forcée
            cmd = [
                "yt-dlp",
                "-x",  # Extract audio from video (force audio extraction even for videos)
                "--audio-format", "m4a",  # Download as m4a first (faster)
                "--audio-quality", "0",  # Best quality
                "--postprocessor-args", "ffmpeg:-vn",  # Force audio only (no video track)
                "--embed-metadata",  # Embed metadata
                "--embed-thumbnail",  # Embed thumbnail
                "--add-metadata",  # Add metadata
                "--write-thumbnail",  # Write thumbnail to file (webp)
                "--no-warnings",  # Ignore les warnings (signature solving, etc.)
                "--ignore-errors",  # Continue même en cas d'erreurs mineures
                "--cookies-from-browser", "chrome",  # Use browser cookies to avoid bot detection
                "--no-playlist",  # Don't download playlists (we handle that separately)
                "-o", output_template,
                url
            ]
            
            # Add ffmpeg location if available (insert before -o)
            if ffmpeg_args:
                # Insert ffmpeg location before -o option
                o_index = cmd.index("-o")
                cmd = cmd[:o_index] + ffmpeg_args + cmd[o_index:]
            
            # Execute download
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=settings.DOWNLOAD_TIMEOUT
            )
            
            # Vérifier d'abord si un fichier a été téléchargé (même en cas d'erreur)
            downloaded_file = self._find_downloaded_file(self.downloads_dir)
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                
                # Si un fichier a été téléchargé malgré l'erreur, c'est probablement juste des warnings
                if downloaded_file:
                    logger.warning(f"yt-dlp returned non-zero but file was downloaded: {downloaded_file}")
                    logger.debug(f"yt-dlp warnings: {error_msg[:500]}")
                    # Keep metadata that was extracted before download
                    logger.info(f"Returning metadata: {metadata}")
                    return downloaded_file, metadata
                
                # Filtrer les warnings pour ne garder que les vraies erreurs
                error_lines = []
                critical_errors = ['ERROR:', 'error:', 'Did not get any data blocks', 'No video formats found']
                
                for line in error_msg.split('\n'):
                    line = line.strip()
                    # Ignorer les warnings sur signature solving (normaux avec YouTube)
                    if line and not line.startswith('WARNING:'):
                        # Vérifier si c'est une erreur critique
                        if any(critical in line for critical in critical_errors):
                            error_lines.append(line)
                
                if error_lines:
                    error_msg = '\n'.join(error_lines[:5])  # Limiter à 5 lignes
                    logger.error(f"yt-dlp error: {error_msg}")
                    raise Exception(f"YouTube download failed: {error_msg}")
                else:
                    # Si seulement des warnings et pas de fichier, c'est un échec
                    raise Exception("Download failed: No file was downloaded and yt-dlp returned an error")
            
            # Si pas d'erreur, vérifier que le fichier existe
            if not downloaded_file:
                raise Exception("Download completed but no file was found")
            
            # Merge metadata from URL with file metadata
            # Metadata from URL includes: artist, thumbnail, uploader, etc.
            # File metadata will be extracted by MetadataService later
            
            return downloaded_file, metadata
            
        except subprocess.TimeoutExpired:
            raise Exception("Download timeout exceeded")
        except Exception as e:
            raise Exception(f"YouTube download failed: {str(e)}")
    
    def download(self, url: str, source: Optional[SourceType] = None) -> Tuple[Optional[Path], dict, SourceType]:
        """
        Download audio from URL (auto-detect source if not provided)
        
        Returns:
            Tuple of (file_path, metadata_dict, source_type)
        """
        if source is None:
            source = self.detect_source(url)
        
        if source == SourceType.YOUTUBE:
            file_path, metadata = self.download_from_youtube(url)
        else:
            raise ValueError(f"Unsupported source type: {source}. Only YouTube and YouTube Music are supported.")
        
        return file_path, metadata, source
    
    def _find_downloaded_file(self, directory: Path) -> Optional[Path]:
        """Find the most recently downloaded file in directory"""
        # Chercher d'abord les formats audio courants (flac en priorité maintenant)
        audio_extensions = ["flac", "m4a", "opus", "mp3", "webm", "ogg", "aac", "wav"]
        
        # Get all audio files (exclude .webp thumbnails)
        audio_files = []
        for ext in audio_extensions:
            files = [f for f in directory.glob(f"*.{ext}") if f.suffix.lower() == f".{ext}"]
            audio_files.extend(files)
        
        if audio_files:
            # Return the most recently modified file
            return max(audio_files, key=lambda f: f.stat().st_mtime)
        
        # If no audio file found, check what files exist
        all_files = [f for f in directory.glob("*") if f.is_file() and not f.name.startswith(".")]
        # Exclude .webp thumbnails
        relevant_files = [f for f in all_files if f.suffix.lower() != ".webp"]
        
        if not relevant_files:
            logger.warning(f"No files found in {directory}")
            return None
        
        # Log what we found
        logger.warning(f"No audio file found in {directory}. Available files: {[f.name for f in relevant_files[:5]]}")
        
        # If we have a .mp4, try to convert it to audio
        mp4_files = [f for f in relevant_files if f.suffix.lower() == ".mp4"]
        if mp4_files:
            logger.warning(f"yt-dlp downloaded .mp4 instead of audio. Attempting to extract audio from video...")
            mp4_file = max(mp4_files, key=lambda f: f.stat().st_mtime)  # Get most recent
            
            # Try to extract audio from mp4 using ffmpeg
            try:
                audio_file = self._extract_audio_from_video(mp4_file)
                if audio_file and audio_file.exists():
                    logger.info(f"Successfully extracted audio from {mp4_file.name} to {audio_file.name}")
                    # Remove the original mp4 file
                    try:
                        mp4_file.unlink()
                        logger.info(f"Removed original video file: {mp4_file.name}")
                    except Exception as e:
                        logger.warning(f"Could not remove original video file: {e}")
                    # Return the converted audio file
                    return audio_file
            except Exception as e:
                logger.error(f"Failed to extract audio from {mp4_file.name}: {e}")
                # If conversion fails, return None (will cause download to fail)
                return None
        
        return None
    
    def _extract_audio_from_video(self, video_file: Path) -> Optional[Path]:
        """Extract audio from a video file using ffmpeg"""
        try:
            # Find ffmpeg
            spotdl_dir = Path.home() / ".spotdl"
            ffmpeg_path = None
            if (spotdl_dir / "ffmpeg").exists():
                ffmpeg_path = str(spotdl_dir / "ffmpeg")
            else:
                import shutil
                ffmpeg_path = shutil.which("ffmpeg")
            
            if not ffmpeg_path:
                raise Exception("ffmpeg not found")
            
            # Output audio file (m4a format)
            audio_file = video_file.parent / f"{video_file.stem}.m4a"
            
            # Extract audio using ffmpeg
            cmd = [
                ffmpeg_path,
                "-i", str(video_file),
                "-vn",  # No video
                "-acodec", "copy",  # Copy audio codec if possible
                "-y",  # Overwrite output file
                str(audio_file)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                # Try with aac codec if copy fails
                cmd = [
                    ffmpeg_path,
                    "-i", str(video_file),
                    "-vn",  # No video
                    "-acodec", "aac",  # Use AAC codec
                    "-b:a", "192k",  # Audio bitrate
                    "-y",  # Overwrite output file
                    str(audio_file)
                ]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60
                )
            
            if result.returncode == 0 and audio_file.exists():
                return audio_file
            else:
                raise Exception(f"ffmpeg failed: {result.stderr}")
                
        except Exception as e:
            logger.error(f"Error extracting audio from video: {e}")
            return None
    
    def _extract_metadata_from_url(self, url: str) -> dict:
        """Extract metadata from YouTube URL before downloading"""
        try:
            import json
            
            # Check for spotdl's ffmpeg if system ffmpeg is not available
            spotdl_dir = Path.home() / ".spotdl"
            ffmpeg_args = []
            if (spotdl_dir / "ffmpeg").exists():
                ffmpeg_path = spotdl_dir / "ffmpeg"
                ffmpeg_args = ["--ffmpeg-location", str(ffmpeg_path)]
            
            cmd = [
                "yt-dlp",
                "--dump-json",
                "--no-warnings",
                "--cookies-from-browser", "chrome",
                url
            ]
            
            # Add ffmpeg location if available
            if ffmpeg_args:
                cmd = cmd[:-1] + ffmpeg_args + [cmd[-1]]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    
                    # Try to extract album from various fields
                    album = data.get("album")
                    if not album:
                        # Try playlist title if it's from a playlist/album
                        album = data.get("playlist") or data.get("playlist_title")
                    if not album:
                        # Try series (sometimes used for albums on YouTube Music)
                        album = data.get("series")
                    if not album:
                        # Try album_artist field
                        album = data.get("album_artist")
                    if not album:
                        # Try to extract from description or other metadata
                        description = data.get("description", "")
                        # Look for "Album:" or "Album :" in description
                        import re
                        album_match = re.search(r'[Aa]lbum\s*:?\s*([^\n]+)', description)
                        if album_match:
                            album = album_match.group(1).strip()
                    if not album:
                        # Last resort: check if URL contains playlist info
                        if "list=" in url:
                            # Try to get playlist name from URL
                            logger.debug("Album not found in metadata, URL contains playlist but album name not extracted")
                    
                    metadata = {
                        "title": data.get("title"),
                        "artist": data.get("artist") or data.get("uploader") or data.get("channel"),
                        "album": album,
                        "thumbnail": data.get("thumbnail"),
                        "uploader": data.get("uploader"),
                        "channel": data.get("channel"),
                        "duration": data.get("duration"),
                        "year": data.get("release_year") or data.get("upload_date", "")[:4] if data.get("upload_date") else None
                    }
                    logger.info(f"Extracted metadata: artist={metadata.get('artist')}, title={metadata.get('title')}, album={metadata.get('album')}")
                    return metadata
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse metadata JSON: {e}")
            
            return {}
            
        except subprocess.TimeoutExpired:
            logger.warning("Metadata extraction timed out, continuing without metadata")
            return {}
        except Exception as e:
            logger.warning(f"Failed to extract metadata from URL: {e}")
            return {}
    
    def convert_to_flac_with_thumbnail(self, m4a_file: Path, thumbnail_url: Optional[str] = None) -> Path:
        """Convert m4a file to FLAC and embed thumbnail webp"""
        try:
            import shutil
            
            if not m4a_file.exists():
                logger.error(f"m4a file does not exist: {m4a_file}")
                return m4a_file
            
            # Find ffmpeg
            spotdl_dir = Path.home() / ".spotdl"
            ffmpeg_path = None
            if (spotdl_dir / "ffmpeg").exists():
                ffmpeg_path = str(spotdl_dir / "ffmpeg")
            else:
                ffmpeg_path = shutil.which("ffmpeg")
            
            if not ffmpeg_path:
                logger.error("ffmpeg not found, cannot convert to FLAC")
                raise Exception("ffmpeg not found")
            
            logger.info(f"Using ffmpeg: {ffmpeg_path}")
            
            # Output FLAC file (same directory as m4a)
            flac_file = m4a_file.parent / f"{m4a_file.stem}.flac"
            logger.info(f"Converting {m4a_file} to {flac_file}")
            
            # Find thumbnail webp file in downloads directory
            thumbnail_file = None
            if thumbnail_url:
                # Try to find webp file with same name as m4a
                webp_file = m4a_file.parent / f"{m4a_file.stem}.webp"
                if webp_file.exists():
                    thumbnail_file = webp_file
                    logger.info(f"Found thumbnail: {thumbnail_file}")
            
            # If no webp found, try to find any webp in downloads
            if not thumbnail_file:
                webp_files = list(m4a_file.parent.glob("*.webp"))
                if webp_files:
                    # Get the most recent webp file
                    thumbnail_file = max(webp_files, key=lambda f: f.stat().st_mtime)
                    logger.info(f"Using thumbnail: {thumbnail_file}")
            
            # Convert m4a to flac with ffmpeg
            # First, convert audio only
            cmd = [
                ffmpeg_path,
                "-i", str(m4a_file),
                "-c:a", "flac",  # FLAC codec
                "-compression_level", "8",  # Best compression
                "-y",  # Overwrite output file
                str(flac_file)
            ]
            
            logger.info(f"Step 1: Converting audio to FLAC...")
            logger.info(f"ffmpeg command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                logger.error(f"ffmpeg audio conversion failed (returncode: {result.returncode})")
                logger.error(f"ffmpeg stderr: {error_msg[:1000]}")
                if result.stdout:
                    logger.error(f"ffmpeg stdout: {result.stdout[:500]}")
                raise Exception(f"FLAC audio conversion failed: {error_msg[:200]}")
            
            if not flac_file.exists():
                logger.error(f"FLAC file was not created: {flac_file}")
                raise Exception("FLAC file was not created")
            
            logger.info(f"✅ Audio converted to FLAC: {flac_file}")
            
            # Step 2: Add thumbnail if found (using mutagen for FLAC)
            if thumbnail_file and thumbnail_file.exists():
                logger.info(f"Step 2: Embedding thumbnail {thumbnail_file.name} into FLAC...")
                try:
                    from mutagen.flac import FLAC, Picture
                    from mutagen import File
                    
                    audio = FLAC(str(flac_file))
                    
                    # Read thumbnail
                    with open(thumbnail_file, 'rb') as f:
                        image_data = f.read()
                    
                    # Create picture
                    picture = Picture()
                    picture.type = 3  # Cover (front)
                    picture.mime = "image/webp"
                    picture.data = image_data
                    picture.width = 0
                    picture.height = 0
                    picture.depth = 0
                    
                    # Add picture to FLAC
                    audio.add_picture(picture)
                    audio.save()
                    
                    logger.info(f"✅ Thumbnail embedded successfully")
                except Exception as e:
                    logger.warning(f"Failed to embed thumbnail with mutagen: {e}")
                    logger.warning("Continuing without thumbnail...")
            
            # Remove original m4a file
            try:
                m4a_file.unlink()
                logger.info(f"Removed original m4a file: {m4a_file.name}")
            except Exception as e:
                logger.warning(f"Could not remove original m4a file: {e}")
            
            # Remove thumbnail webp if it was used
            if thumbnail_file and thumbnail_file.exists():
                try:
                    thumbnail_file.unlink()
                    logger.info(f"Removed thumbnail file: {thumbnail_file.name}")
                except Exception as e:
                    logger.warning(f"Could not remove thumbnail file: {e}")
            
            logger.info(f"✅ Successfully converted to FLAC: {flac_file.name}")
            return flac_file
            
        except Exception as e:
            logger.error(f"Error converting to FLAC: {e}")
            logger.exception("Full traceback:")
            # Don't return original file if conversion fails - raise exception instead
            raise Exception(f"Failed to convert {m4a_file.name} to FLAC: {str(e)}")

