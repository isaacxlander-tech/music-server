"""YouTube Music downloader"""
import subprocess
import re
import uuid
import time
import logging
from pathlib import Path
from typing import Optional, Tuple
from app.config import settings
from app.services.downloader.base import BaseDownloader
from app.services.downloader.utils import (
    find_downloaded_file,
    get_ffmpeg_path
)

logger = logging.getLogger(__name__)


class YouTubeDownloader(BaseDownloader):
    """Downloader for YouTube Music"""
    
    def __init__(self):
        self.downloads_dir = settings.DOWNLOADS_DIR
        
        # Get yt-dlp path from venv
        self.ytdlp_cmd = "/opt/music-home/venv/bin/yt-dlp"
        if not Path(self.ytdlp_cmd).exists():
            logger.warning(f"yt-dlp not found at {self.ytdlp_cmd}, using system command")
            self.ytdlp_cmd = "yt-dlp"
        else:
            logger.info(f"Using yt-dlp from: {self.ytdlp_cmd}")
    
    def download(self, url: str) -> Tuple[Optional[Path], dict]:
        """
        Download audio from YouTube Music using yt-dlp
        
        Returns:
            Tuple of (file_path, metadata_dict)
        """
        try:
            # Check if yt-dlp is available
            try:
                subprocess.run([self.ytdlp_cmd, "--version"], capture_output=True, check=True, timeout=5)
            except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
                raise Exception("yt-dlp n'est pas installé ou n'est pas dans le PATH. Installez-le avec: pip install yt-dlp")
            
            # First, extract metadata from URL (artist, thumbnail, etc.)
            metadata = self.extract_metadata(url)
            
            # Générer un ID unique pour éviter les conflits de noms de fichiers
            unique_id = f"{int(time.time())}_{uuid.uuid4().hex[:8]}"
            
            # Prepare output template with unique ID to avoid conflicts
            output_template = str(self.downloads_dir / f"%(title)s_{unique_id}.%(ext)s")
            
            logger.info(f"Downloading from YouTube: {url}")
            
            # Check for spotdl's ffmpeg if system ffmpeg is not available
            ffmpeg_path = get_ffmpeg_path()
            ffmpeg_args = []
            if ffmpeg_path:
                ffmpeg_args = ["--ffmpeg-location", ffmpeg_path]
                logger.info(f"Using ffmpeg from: {ffmpeg_path}")
            else:
                logger.warning("ffmpeg not found! Audio extraction may fail. Install ffmpeg or ensure spotdl's ffmpeg is available.")
            
            # Build base command - télécharger directement le meilleur format audio (plus rapide)
            # Utilise -x pour extraire l'audio du meilleur format disponible (m4a, opus, mp3)
            # Beaucoup plus rapide que la conversion FLAC forcée
            cmd = [
                self.ytdlp_cmd,
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
            downloaded_file = find_downloaded_file(self.downloads_dir)
            
            # Gérer les fichiers .temp.m4a qui peuvent être renommés
            if downloaded_file and downloaded_file.name.endswith('.temp.m4a'):
                logger.info(f"Found .temp.m4a file, waiting for rename: {downloaded_file.name}")
                m4a_file = downloaded_file.with_suffix('').with_suffix('.m4a')
                for _ in range(20):  # Attendre jusqu'à 10 secondes
                    time.sleep(0.5)
                    if m4a_file.exists():
                        logger.info(f"Temp file renamed: {downloaded_file.name} -> {m4a_file.name}")
                        downloaded_file = m4a_file
                        break
                else:
                    # Si après 10s le fichier n'est toujours pas renommé, renommer manuellement
                    logger.warning(f"Temp file not renamed after 10s, renaming manually: {downloaded_file.name}")
                    try:
                        downloaded_file.rename(m4a_file)
                        logger.info(f"Manually renamed: {downloaded_file.name} -> {m4a_file.name}")
                        downloaded_file = m4a_file
                    except Exception as e:
                        logger.warning(f"Could not rename temp file: {e}, using temp file")
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                
                # Si un fichier a été téléchargé malgré l'erreur, attendre qu'il soit complet
                if downloaded_file:
                    logger.warning(f"yt-dlp returned non-zero but file was downloaded: {downloaded_file}")
                    logger.debug(f"yt-dlp warnings: {error_msg[:500]}")
                    
                    # Attendre que le fichier soit complètement téléchargé
                    max_wait = 15  # Maximum 15 secondes d'attente
                    wait_interval = 0.5
                    waited = 0
                    
                    previous_size = 0
                    stable_count = 0
                    required_stable_checks = 4  # Le fichier doit être stable pendant 4 vérifications (2 secondes)
                    
                    logger.info(f"Waiting for download to complete: {downloaded_file.name}")
                    while waited < max_wait:
                        if not downloaded_file.exists():
                            break
                        current_size = downloaded_file.stat().st_size
                        
                        if current_size == previous_size and current_size > 0:
                            stable_count += 1
                            if stable_count >= required_stable_checks:
                                logger.info(f"Download complete, file size stable at {current_size} bytes after {waited:.1f}s")
                                break
                        else:
                            stable_count = 0
                            previous_size = current_size
                        
                        time.sleep(wait_interval)
                        waited += wait_interval
                    
                    if waited >= max_wait:
                        logger.warning(f"File size did not stabilize after {max_wait}s, proceeding anyway")
                    
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
    
    def extract_metadata(self, url: str) -> dict:
        """Extract metadata from YouTube URL before downloading"""
        try:
            import json
            
            # Check for spotdl's ffmpeg if system ffmpeg is not available
            ffmpeg_path = get_ffmpeg_path()
            ffmpeg_args = []
            if ffmpeg_path:
                ffmpeg_args = ["--ffmpeg-location", ffmpeg_path]
            
            cmd = [
                self.ytdlp_cmd,
                "--dump-json",
                "--no-warnings",
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
