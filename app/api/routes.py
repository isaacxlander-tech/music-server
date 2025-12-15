"""API routes for music server"""
import logging
import os
import subprocess
from fastapi import APIRouter, Depends, HTTPException, Query, Header, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import or_
from typing import List, Optional
from pathlib import Path

from app.database.db import get_db, SessionLocal
from app.models.track import Track, SourceType
from app.models.schemas import (
    TrackResponse,
    DownloadRequest,
    DownloadResponse,
    SearchQuery,
    QueueAddRequest,
    QueueAddMultipleRequest,
    AlbumExtractRequest
)
from app.services.downloader import DownloaderService
from app.services.metadata import MetadataService
from app.services.organizer import OrganizerService
from app.services.plex import PlexService
from app.services.music_sorter import MusicSorterService
from app.services.artist_cleanup import ArtistCleanupService
from app.services.task_manager import task_manager, TaskStatus
from app.services.queue_manager import get_queue_manager
from app.models.queue import QueueStatus
from app.api.auth import get_current_user_id
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

downloader_service = DownloaderService()
metadata_service = MetadataService()
organizer_service = OrganizerService()
plex_service = PlexService()
queue_manager = get_queue_manager(task_manager)

# Get yt-dlp path from venv
YTDLP_CMD = "/opt/music-home/venv/bin/yt-dlp"
if not Path(YTDLP_CMD).exists():
    logger.warning(f"yt-dlp not found at {YTDLP_CMD}, using system command")
    YTDLP_CMD = "yt-dlp"
else:
    logger.info(f"Using yt-dlp from: {YTDLP_CMD}")


def process_download_sync(url: str, task_id: str, queue_item_id: int):
    """Synchronous background task to process download (for thread pool execution)"""
    db = SessionLocal()
    queue_item = None
    try:
        # Get queue item by id
        queue_item = queue_manager.get_item_by_task_id(task_id)
        if not queue_item:
            queue_item = queue_manager.get_item_by_url(url)
        
        # Get source from queue_item (convert to SourceType if needed)
        source = queue_item.source if queue_item else None
        if source and isinstance(source, str):
            try:
                source = SourceType[source.upper()] if source.upper() in SourceType.__members__ else SourceType(source)
            except (ValueError, KeyError):
                logger.warning(f"Invalid source in queue_item: {source}, will auto-detect")
                source = None
        
        # Update queue item
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.PROCESSING,
                progress=5,
                message="Préparation du téléchargement..."
            )
        
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 5, "Préparation du téléchargement...")
        
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.PROCESSING,
                progress=15,
                message="Téléchargement en cours..."
            )
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 15, "Téléchargement en cours...")
        
        # Download file (maintenant beaucoup plus rapide - télécharge directement le meilleur format)
        file_path, download_metadata, detected_source = downloader_service.download(
            url,
            source
        )
        
        if file_path is None:
            raise Exception("Download completed but file not found")
        
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.PROCESSING,
                progress=50,
                message="Téléchargement terminé, conversion en FLAC..."
            )
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 50, "Téléchargement terminé, conversion en FLAC...")
        logger.info(f"File downloaded to: {file_path}")
        platform_name = detected_source.value.capitalize() if detected_source else "platform"
        logger.info(f"Download metadata from {platform_name}: {download_metadata}")
        
        # Vérifier si le fichier existe encore dans downloads/ (peut avoir été déplacé par un autre processus)
        if not file_path.exists():
            # Chercher dans music/ si le fichier a été déplacé
            logger.warning(f"File not found in downloads: {file_path.name}, searching in music directory...")
            from app.config import settings
            music_dir = settings.MUSIC_DIR
            file_name = file_path.name
            
            # Chercher récursivement dans music/
            found_in_music = None
            for flac_in_music in music_dir.rglob(file_name):
                if flac_in_music.exists() and flac_in_music.stat().st_size > 0:
                    found_in_music = flac_in_music
                    logger.info(f"File found in music directory (was moved by another process): {flac_in_music}")
                    break
            
            if found_in_music:
                # Vérifier si le track existe déjà dans la base de données
                existing_track = db.query(Track).filter(
                    (Track.file_path == str(found_in_music)) | 
                    (Track.source_url == url)
                ).first()
                
                if existing_track:
                    logger.info(f"Track already exists in database, skipping processing: {existing_track.id}")
                    if queue_item:
                        queue_manager.update_item_status(
                            queue_item.id,
                            QueueStatus.COMPLETED,
                            progress=100,
                            message="Déjà téléchargé"
                        )
                    task_manager.update_task(task_id, TaskStatus.COMPLETED, 100, "Déjà téléchargé")
                    return
                else:
                    # Le fichier existe dans music/ mais pas dans la DB, utiliser ce fichier
                    file_path = found_in_music
                    logger.info(f"Using file from music directory: {file_path}")
            else:
                raise FileNotFoundError(f"File not found in downloads or music: {file_path.name}")
        
        # Convert m4a to flac and embed thumbnail webp
        if file_path.suffix.lower() == ".m4a":
            logger.info(f"Converting {file_path.name} to FLAC...")
            original_path = file_path
            file_path = downloader_service.convert_to_flac_with_thumbnail(file_path, download_metadata.get("thumbnail"))
            if file_path.suffix.lower() != ".flac":
                logger.error(f"Conversion failed! File is still {file_path.suffix}, expected .flac")
                logger.error(f"Original: {original_path}, Result: {file_path}")
            else:
                logger.info(f"✅ Successfully converted to FLAC: {file_path}")
                # After conversion, we need to write metadata to the FLAC file
                # The metadata will be written later in organizer_service
        
        # Vérifier à nouveau si le fichier existe (peut avoir été déplacé pendant la conversion)
        if not file_path.exists():
            # Chercher dans music/ si le fichier a été déplacé
            logger.warning(f"File not found after conversion: {file_path.name}, searching in music directory...")
            from app.config import settings
            music_dir = settings.MUSIC_DIR
            file_name = file_path.name
            
            # Chercher récursivement dans music/
            found_in_music = None
            for flac_in_music in music_dir.rglob(file_name):
                if flac_in_music.exists() and flac_in_music.stat().st_size > 0:
                    found_in_music = flac_in_music
                    logger.info(f"File found in music directory (was moved during conversion): {flac_in_music}")
                    break
            
            if found_in_music:
                file_path = found_in_music
                logger.info(f"Using file from music directory: {file_path}")
            else:
                raise FileNotFoundError(f"File not found after conversion: {file_path.name}")
        
        # Extract metadata from downloaded file
        file_metadata = metadata_service.extract_metadata(file_path)
        logger.info(f"Metadata extracted from file: {file_metadata}")
        
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.PROCESSING,
                progress=60,
                message="Organisation du fichier..."
            )
        task_manager.update_task(task_id, TaskStatus.PROCESSING, 60, "Organisation du fichier...")
        
        # Helper function to clean title from suffix
        def clean_title_from_suffix(title: str) -> str:
            """Remove timestamp/hash suffix from title (e.g., 'Title_1234567890_abc123' -> 'Title')"""
            if not title:
                return title
            import re
            # Pattern: Title_timestamp_hash
            match = re.match(r'^(.+?)_\d+_[a-f0-9]+$', title)
            if match:
                return match.group(1)
            return title
        
        # Merge with download metadata (from yt-dlp)
        if download_metadata:
            # Prioritize download metadata over file metadata (more accurate from platform)
            if download_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("artist")
            elif download_metadata.get("uploader") and not file_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("uploader")
            elif download_metadata.get("channel") and not file_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("channel")
            
            # Always prioritize download metadata title, or clean file metadata title
            if download_metadata.get("title"):
                file_metadata["title"] = download_metadata.get("title")
            elif file_metadata.get("title"):
                # Clean title from suffix if it contains one
                file_metadata["title"] = clean_title_from_suffix(file_metadata.get("title"))
            
            # Always use album from download metadata if available
            if download_metadata.get("album"):
                file_metadata["album"] = download_metadata.get("album")
                logger.info(f"✅ Using album from YouTube metadata: {download_metadata.get('album')}")
            elif not file_metadata.get("album"):
                # If no album found, try to extract from URL or use a default
                logger.warning("⚠️ No album found in metadata, will use 'Unknown Album'")
                file_metadata["album"] = "Unknown Album"
            
            if download_metadata.get("year") and not file_metadata.get("year"):
                file_metadata["year"] = download_metadata.get("year")
            
            # Store thumbnail URL for later use (if needed)
            if download_metadata.get("thumbnail"):
                file_metadata["thumbnail"] = download_metadata.get("thumbnail")
        
        # Normalize metadata
        file_metadata = metadata_service.normalize_metadata(file_metadata)
        
        # Ensure album is set (required for Plex)
        if not file_metadata.get("album"):
            file_metadata["album"] = "Unknown Album"
            logger.warning("⚠️ Album not found in metadata, using 'Unknown Album'")
        
        logger.info(f"Final metadata before organization: artist={file_metadata.get('artist')}, title={file_metadata.get('title')}, album={file_metadata.get('album')}")
        
        # Vérifier si le fichier est déjà dans music/ (peut avoir été déplacé par un autre processus)
        from app.config import settings
        if str(file_path).startswith(str(settings.MUSIC_DIR)):
            logger.info(f"File is already in music directory, skipping organization: {file_path}")
            organized_path = file_path
        else:
            # Organize file in Plex structure (move from downloads to music)
            organized_path = organizer_service.organize_file(file_path, file_metadata)
            logger.info(f"File organized to: {organized_path}")
        
        # Verify file is in music directory, not downloads
        if not str(organized_path).startswith(str(settings.MUSIC_DIR)):
            logger.error(f"ERROR: File organized to wrong location! Expected in {settings.MUSIC_DIR}, got {organized_path}")
            raise Exception(f"File not organized correctly: {organized_path}")
        
        # Verify file exists
        if not organized_path.exists():
            logger.error(f"ERROR: Organized file does not exist: {organized_path}")
            raise FileNotFoundError(f"Organized file not found: {organized_path}")
        
        logger.info(f"✅ File successfully moved to music directory: {organized_path}")
        
        if queue_item:
            queue_item.progress = 80
            queue_item.message = "Sauvegarde dans la base de données..."
        task_manager.update_task(task_id, TaskStatus.PROCESSING, 80, "Sauvegarde dans la base de données...")
        
        # Check if track already exists (by file_path or source_url)
        existing_track = db.query(Track).filter(
            (Track.file_path == str(organized_path)) | 
            (Track.source_url == url)
        ).first()
        
        if existing_track:
            # Update existing track
            logger.info(f"Track already exists (ID: {existing_track.id}), updating...")
            existing_track.artist = file_metadata.get("artist") or "Unknown Artist"
            existing_track.album = file_metadata.get("album")
            existing_track.title = file_metadata.get("title") or file_path.stem
            existing_track.year = file_metadata.get("year")
            existing_track.genre = file_metadata.get("genre")
            existing_track.duration = file_metadata.get("duration")
            existing_track.file_path = str(organized_path)
            existing_track.file_size = file_metadata.get("file_size")
            existing_track.source = detected_source
            existing_track.source_url = url
            track = existing_track
        else:
            # Create new track record
            track = Track(
                artist=file_metadata.get("artist") or "Unknown Artist",
                album=file_metadata.get("album"),
                title=file_metadata.get("title") or file_path.stem,
                year=file_metadata.get("year"),
                genre=file_metadata.get("genre"),
                duration=file_metadata.get("duration"),
                file_path=str(organized_path),
                file_size=file_metadata.get("file_size"),
                source=detected_source,
                source_url=url
            )
            db.add(track)
        
        db.commit()
        db.refresh(track)
        logger.info(f"Track saved to database with ID: {track.id}")
        
        # Déclencher le scan Plex si configuré
        if settings.PLEX_AUTO_SCAN:
            try:
                plex_service.scan_library()
                logger.info("Plex scan triggered")
            except Exception as e:
                logger.warning(f"Failed to trigger Plex scan: {str(e)}")
        
        task_manager.update_task(task_id, TaskStatus.COMPLETED, 100, f"Téléchargement terminé: {track.title}", track_id=track.id)
        
        # Update queue item to completed
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.COMPLETED,
                progress=100,
                message=f"Téléchargement terminé: {track.title}",
                title=track.title
            )
        
    except Exception as e:
        logger.exception(f"Error in download task {task_id}: {str(e)}")
        task_manager.update_task(task_id, error=str(e))
        
        # Update queue item to failed
        if queue_item:
            queue_manager.update_item_status(
                queue_item.id,
                QueueStatus.FAILED,
                progress=0,
                message="Échec du téléchargement",
                error=str(e)
            )
        db.rollback()
    finally:
        db.close()


@router.post("/download")
async def download_music(
    request: DownloadRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Add music to download queue (sequential processing)
    
    Returns queue info, use /queue to check status
    """
    try:
        logger.info(f"Adding to queue: {request.url}")
        
        # Add to queue instead of downloading immediately
        item = queue_manager.add_to_queue(request.url, request.source, None)  # Title will be set during download

        return {
            "success": True,
            "message": "Ajouté à la queue de téléchargement",
            "queue_size": queue_manager.get_queue_size(),
            "item": item  # item is already a dict
        }
        
    except Exception as e:
        logger.exception(f"Failed to add to queue: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to add to queue: {str(e)}"
        )


@router.get("/download/status/{task_id}")
async def get_download_status(
    task_id: str,
    user_id: int = Depends(get_current_user_id)
):
    """Get download task status"""
    task = task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return task.to_dict()


# Queue endpoints
@router.post("/queue/add")
async def add_to_queue(
    request: QueueAddRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Add URL to download queue"""
    try:
        item = queue_manager.add_to_queue(request.url, request.source, request.title)
        return {
            "success": True,
            "message": "URL ajoutée à la queue",
            "queue_size": queue_manager.get_queue_size(),
            "item": item  # item is already a dict
        }
    except Exception as e:
        logger.exception(f"Failed to add to queue: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to add to queue: {str(e)}")


@router.post("/queue/add-multiple")
async def add_multiple_to_queue(
    request: QueueAddMultipleRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Add multiple URLs to download queue"""
    try:
        items = []
        titles = request.titles or []
        for i, url in enumerate(request.urls):
            title = titles[i] if i < len(titles) else None
            item = queue_manager.add_to_queue(url, request.source, title)
            items.append(item)
        return {
            "success": True,
            "message": f"{len(request.urls)} URLs ajoutées à la queue",
            "queue_size": queue_manager.get_queue_size(),
            "items": [item if isinstance(item, dict) else item.to_dict() for item in items]
        }
    except Exception as e:
        logger.exception(f"Failed to add to queue: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to add to queue: {str(e)}")


@router.post("/search")
async def search_url(
    request: AlbumExtractRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Search/extract information from YouTube/YouTube Music URL (album, playlist, or single track)"""
    try:
        import subprocess
        import json
        
        url = request.url
        
        # Check if it's a playlist/album or single track
        is_playlist = "list=" in url or "playlist" in url.lower()
        
        if is_playlist:
            # Extract playlist/album information
            cmd = [
                YTDLP_CMD,
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                url
            ]
            
            logger.info(f"Extracting playlist, timeout: 300s")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minutes for playlists
                )
            except subprocess.TimeoutExpired:
                logger.error("Playlist extraction timed out after 300 seconds")
                raise Exception("L'extraction de la playlist a pris trop de temps. Essayez avec une playlist plus petite ou réessayez plus tard.")
            
            # Parse tracks even if returncode != 0 (might have warnings but still got data)
            tracks = []
            if result.stdout.strip():
                # We have data, try to parse it
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        try:
                            data = json.loads(line)
                            video_id = data.get('id', '')
                            if not video_id:
                                # Try to extract from url field
                                url_field = data.get('url', '')
                                if 'v=' in url_field:
                                    video_id = url_field.split('v=')[-1].split('&')[0]
                            
                            if not video_id:
                                continue
                                
                            title = data.get('title', 'Unknown')
                            duration = data.get('duration', 0)
                            
                            # Construct URL
                            if 'music.youtube.com' in url:
                                track_url = f"https://music.youtube.com/watch?v={video_id}"
                            else:
                                track_url = f"https://www.youtube.com/watch?v={video_id}"
                            
                            tracks.append({
                                "id": video_id,
                                "title": title,
                                "duration": duration,
                                "url": track_url,
                                "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                            })
                        except (json.JSONDecodeError, KeyError, IndexError, AttributeError) as e:
                            logger.debug(f"Failed to parse track line: {e}")
                            continue
            
            if result.returncode != 0 and not tracks:
                error_msg = result.stderr or result.stdout
                # No data, real error
                error_lines = [line for line in error_msg.split('\n') 
                             if line.strip() and not line.startswith('WARNING:')]
                if error_lines:
                    raise Exception(f"Failed to extract playlist: {' '.join(error_lines[:3])}")
                else:
                    raise Exception(f"Failed to extract playlist: {error_msg[:200]}")
            
            if not tracks:
                raise Exception("Aucune musique trouvée dans la playlist")
            
            # Get playlist info (use first track URL or playlist URL)
            # Try to get info from first track if available, otherwise skip
            playlist_info = {
                "title": "Unknown Album",
                "uploader": "Unknown Artist",
                "thumbnail": None
            }
            
            # Try to get playlist info from first track if we have tracks
            if tracks:
                try:
                    first_track_url = tracks[0]["url"]
                    playlist_cmd = [
                        YTDLP_CMD,
                        "--dump-json",
                        "--no-warnings",
                        first_track_url
                    ]
                    
                    playlist_result = subprocess.run(
                        playlist_cmd,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    
                    if playlist_result.returncode == 0:
                        playlist_data = json.loads(playlist_result.stdout)
                        # Try to extract album/playlist info
                        playlist_info = {
                            "title": playlist_data.get('album') or playlist_data.get('playlist') or playlist_data.get('title', 'Unknown Album'),
                            "uploader": playlist_data.get('artist') or playlist_data.get('uploader') or playlist_data.get('channel', 'Unknown Artist'),
                            "thumbnail": playlist_data.get('thumbnail')
                        }
                except Exception as e:
                    logger.debug(f"Failed to get playlist info: {e}")
                    # Use default info
            
            
            return {
                "success": True,
                "type": "playlist",
                "playlist_info": playlist_info,
                "tracks": tracks,
                "count": len(tracks)
            }
        else:
            # Single track - get information
            cmd = [
                YTDLP_CMD,
                "--dump-json",
                "--no-warnings",
                url
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Increased timeout for single tracks too
            )
            
            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                # Filter out warnings
                error_lines = [line for line in error_msg.split('\n') 
                             if line.strip() and not line.startswith('WARNING:')]
                if error_lines:
                    raise Exception(f"Failed to extract track info: {' '.join(error_lines[:3])}")
                else:
                    # If only warnings, try to parse anyway
                    pass
            
            data = json.loads(result.stdout)
            video_id = data.get('id', '')
            
            track = {
                "id": video_id,
                "title": data.get('title', 'Unknown'),
                "artist": data.get('uploader') or data.get('channel', 'Unknown Artist'),
                "duration": data.get('duration', 0),
                "url": url,
                "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
            }
            
            return {
                "success": True,
                "type": "track",
                "track": track
            }
        
    except Exception as e:
        logger.exception(f"Failed to search URL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to search URL: {str(e)}")


@router.post("/search/text/quick")
async def search_by_text_quick(
    request: dict,
    user_id: int = Depends(get_current_user_id)
):
    """
    Fast search - returns artists quickly without full metadata extraction
    Uses yt-dlp with minimal options for speed
    """
    try:
        import subprocess
        import json
        
        query = request.get("query", "").strip()
        platform = request.get("platform", "youtube").lower()  # Nouveau paramètre
        limit = request.get("limit", 20)  # More results for better artist grouping
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Construire la requête selon la plateforme
        if platform == "youtube":
            search_query = f"ytsearch{limit}:{query}"
        elif platform == "soundcloud":
            search_query = f"scsearch{limit}:{query}"
        elif platform == "spotify":
            raise HTTPException(status_code=501, detail="Recherche Spotify non encore implémentée")
        else:
            raise HTTPException(status_code=400, detail=f"Plateforme non supportée: {platform}")
        
        # Use --flat-playlist for speed (both YouTube and SoundCloud)
        # For quick search, speed is more important than full metadata
        cmd = [
            YTDLP_CMD,
            "--flat-playlist",  # Faster, no full metadata extraction
            "--dump-json",
            "--no-warnings",
            "--no-playlist",  # Don't extract playlists
            search_query
        ]
        
        logger.info(f"Fast search for: {query} on platform: {platform}")
        # Timeout standard pour recherche rapide
        timeout = 30  # 30 secondes max pour recherche rapide
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            error_lines = [line for line in error_msg.split('\n') 
                         if line.strip() and not line.startswith('WARNING:')]
            if error_lines:
                raise HTTPException(status_code=500, detail=f"Search failed: {' '.join(error_lines[:3])}")
        
        # Parse results and group by artist
        artists_map = {}
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    data = json.loads(line)
                    
                    # Pour SoundCloud, l'ID peut être dans différents champs
                    if platform == "soundcloud":
                        video_id = data.get('id') or data.get('track_id') or data.get('url', '').split('/')[-1] if data.get('url') else ''
                        # Si pas d'ID mais on a une URL, on peut continuer
                        if not video_id and not (data.get('url') or data.get('webpage_url')):
                            logger.debug(f"Skipping SoundCloud result: no ID or URL found")
                            continue
                    else:
                        video_id = data.get('id', '')
                        if not video_id:
                            continue
                    
                    # Extract artist from title or channel
                    title = data.get('title', 'Unknown')
                    if platform == "soundcloud":
                        # SoundCloud peut avoir uploader, creator, ou artist
                        artist = data.get('uploader') or data.get('creator') or data.get('artist') or data.get('channel') or 'Unknown Artist'
                    else:
                        artist = data.get('uploader') or data.get('channel') or 'Unknown Artist'
                    
                    # Construct URL selon la plateforme
                    if platform == "youtube":
                        track_url = f"https://www.youtube.com/watch?v={video_id}"
                    elif platform == "soundcloud":
                        # Pour SoundCloud, utiliser l'URL complète si disponible
                        track_url = data.get('url') or data.get('webpage_url')
                        if not track_url and video_id:
                            # Construire l'URL depuis l'ID si possible
                            uploader_id = data.get('uploader_id') or data.get('uploader', '').lower().replace(' ', '-')
                            track_url = f"https://soundcloud.com/{uploader_id}/{video_id}"
                        if not track_url:
                            logger.debug(f"Skipping SoundCloud track: no URL available")
                            continue
                    else:
                        track_url = data.get('url') or data.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Group by artist
                    if artist not in artists_map:
                        # Thumbnail selon la plateforme (avec --flat-playlist, peut être limité)
                        if platform == "youtube":
                            default_thumbnail = f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                        elif platform == "soundcloud":
                            # Avec --flat-playlist, les thumbnails peuvent ne pas être disponibles
                            default_thumbnail = data.get('thumbnail') or data.get('artwork_url') or data.get('artwork_url_https') or ""
                        else:
                            default_thumbnail = data.get('thumbnail') or ""
                        
                        artists_map[artist] = {
                            "name": artist,
                            "thumbnail": data.get('thumbnail') or data.get('artwork_url') or data.get('artwork_url_https') or default_thumbnail,
                            "tracks": []
                        }
                    
                    # Thumbnail pour les tracks selon la plateforme
                    if platform == "youtube":
                        track_thumbnail = data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                    elif platform == "soundcloud":
                        # Avec --flat-playlist, les thumbnails peuvent ne pas être disponibles
                        track_thumbnail = data.get('thumbnail') or data.get('artwork_url') or data.get('artwork_url_https') or ""
                    else:
                        track_thumbnail = data.get('thumbnail') or ""
                    
                    artists_map[artist]["tracks"].append({
                        "id": video_id,
                        "title": title,
                        "url": track_url,
                        "thumbnail": track_thumbnail
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Failed to parse search result: {e}")
                    continue
        
        # Convert to list
        artists = list(artists_map.values())
        
        if not artists:
            raise HTTPException(status_code=404, detail="Aucun résultat trouvé")
        
        return {
            "success": True,
            "type": "artists",
            "query": query,
            "artists": artists,
            "count": len(artists)
        }
        
    except Exception as e:
        logger.exception(f"Failed to quick search: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}")


@router.post("/search/text")
async def search_by_text(
    request: dict,
    user_id: int = Depends(get_current_user_id)
):
    """
    Search YouTube/YouTube Music by text query (artist, title, album)
    Uses yt-dlp's ytsearch: feature
    Supports different result types: songs, albums, playlists
    """
    try:
        import subprocess
        import json
        
        query = request.get("query", "").strip()
        platform = request.get("platform", "youtube").lower()  # Nouveau paramètre
        result_type = request.get("type", "songs")  # songs, albums, playlists
        limit = request.get("limit", 10)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Construire la requête selon la plateforme
        if platform == "youtube":
            search_query = f"ytsearch{limit}:{query}"
        elif platform == "soundcloud":
            search_query = f"scsearch{limit}:{query}"
        elif platform == "spotify":
            raise HTTPException(status_code=501, detail="Recherche Spotify non encore implémentée")
        else:
            raise HTTPException(status_code=400, detail=f"Plateforme non supportée: {platform}")

        # Use --flat-playlist for speed (both platforms)
        cmd = [
            YTDLP_CMD,
            "--flat-playlist",  # Faster, no full metadata extraction
            "--dump-json",
            "--no-warnings",
            search_query
        ]
        
        logger.info(f"Searching {platform} for: {query} (type: {result_type})")
        timeout = 45  # Timeout standard pour recherche
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            error_lines = [line for line in error_msg.split('\n') 
                         if line.strip() and not line.startswith('WARNING:')]
            if error_lines:
                raise HTTPException(status_code=500, detail=f"Search failed: {' '.join(error_lines[:3])}")
        
        # Parse results
        tracks = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    data = json.loads(line)
                    
                    # Pour SoundCloud, l'ID peut être dans différents champs
                    if platform == "soundcloud":
                        video_id = data.get('id') or data.get('track_id') or data.get('url', '').split('/')[-1] if data.get('url') else ''
                        if not video_id and not (data.get('url') or data.get('webpage_url')):
                            continue
                    else:
                        video_id = data.get('id', '')
                        if not video_id:
                            continue
                    
                    # Construct URL selon la plateforme
                    if platform == "youtube":
                        track_url = f"https://www.youtube.com/watch?v={video_id}"
                    elif platform == "soundcloud":
                        track_url = data.get('url') or data.get('webpage_url')
                        if not track_url and video_id:
                            uploader_id = data.get('uploader_id') or data.get('uploader', '').lower().replace(' ', '-')
                            track_url = f"https://soundcloud.com/{uploader_id}/{video_id}"
                        if not track_url:
                            continue
                    else:
                        track_url = data.get('url') or data.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Extract artist
                    if platform == "soundcloud":
                        artist = data.get('uploader') or data.get('creator') or data.get('artist') or data.get('channel', 'Unknown Artist')
                    else:
                        artist = data.get('uploader') or data.get('channel', 'Unknown Artist')
                    
                    # Thumbnail selon la plateforme (avec --flat-playlist, peut être limité)
                    if platform == "youtube":
                        thumbnail = data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                    elif platform == "soundcloud":
                        thumbnail = data.get('thumbnail') or data.get('artwork_url') or data.get('artwork_url_https') or ""
                    else:
                        thumbnail = data.get('thumbnail') or ""
                    
                    tracks.append({
                        "id": video_id,
                        "title": data.get('title', 'Unknown'),
                        "artist": artist,
                        "duration": data.get('duration', 0),
                        "url": track_url,
                        "thumbnail": thumbnail
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Failed to parse search result: {e}")
                    continue
        
        if not tracks:
            raise HTTPException(status_code=404, detail="Aucun résultat trouvé")
        
        return {
            "success": True,
            "type": "search_results",
            "result_type": result_type,
            "query": query,
            "tracks": tracks,
            "count": len(tracks)
        }
        
    except Exception as e:
        logger.exception(f"Failed to search by text: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}")


@router.post("/search/artist")
async def search_artist_content(
    request: dict,
    user_id: int = Depends(get_current_user_id)
):
    """
    Get content for a specific artist (songs, albums, playlists)
    Fast search using --flat-playlist for speed
    """
    try:
        import subprocess
        import json
        
        artist_name = request.get("artist", "").strip()
        platform = request.get("platform", "youtube").lower()
        content_type = request.get("type", "songs")  # songs, albums, playlists
        limit = request.get("limit", 20)
        
        if not artist_name:
            raise HTTPException(status_code=400, detail="Artist name is required")
        
        # Construire la requête selon la plateforme
        if platform == "youtube":
            search_query = f"ytsearch{limit}:{artist_name}"
        elif platform == "soundcloud":
            search_query = f"scsearch{limit}:{artist_name}"
        elif platform == "spotify":
            raise HTTPException(status_code=501, detail="Recherche Spotify non encore implémentée")
        else:
            raise HTTPException(status_code=400, detail=f"Plateforme non supportée: {platform}")
        
        # Use --flat-playlist for speed (both platforms)
        cmd = [
            YTDLP_CMD,
            "--flat-playlist",  # Faster, no full metadata extraction
            "--dump-json",
            "--no-warnings",
            "--no-playlist",
            search_query
        ]
        
        logger.info(f"Fast search content for artist: {artist_name} on platform: {platform} (type: {content_type})")
        timeout = 30  # Timeout standard pour recherche rapide
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            error_lines = [line for line in error_msg.split('\n') 
                         if line.strip() and not line.startswith('WARNING:')]
            if error_lines:
                raise HTTPException(status_code=500, detail=f"Search failed: {' '.join(error_lines[:3])}")
        
        # Parse results
        tracks = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                try:
                    data = json.loads(line)
                    
                    # Pour SoundCloud, l'ID peut être dans différents champs
                    if platform == "soundcloud":
                        video_id = data.get('id') or data.get('track_id') or data.get('url', '').split('/')[-1] if data.get('url') else ''
                        if not video_id and not (data.get('url') or data.get('webpage_url')):
                            continue
                    else:
                        video_id = data.get('id', '')
                        if not video_id:
                            continue
                    
                    # Extract artist from title or channel
                    title = data.get('title', 'Unknown')
                    if platform == "soundcloud":
                        artist = data.get('uploader') or data.get('creator') or data.get('artist') or data.get('channel') or 'Unknown Artist'
                    else:
                        artist = data.get('uploader') or data.get('channel') or 'Unknown Artist'
                    
                    # Filter by artist if needed (case-insensitive partial match)
                    if artist_name.lower() not in artist.lower() and artist.lower() not in artist_name.lower():
                        continue
                    
                    # Construct URL selon la plateforme
                    if platform == "youtube":
                        track_url = f"https://www.youtube.com/watch?v={video_id}"
                    elif platform == "soundcloud":
                        track_url = data.get('url') or data.get('webpage_url') or f"https://soundcloud.com/{data.get('uploader_id', '')}/{data.get('id', '')}"
                    else:
                        track_url = data.get('url') or data.get('webpage_url') or f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Thumbnail selon la plateforme
                    if platform == "youtube":
                        thumbnail = data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
                    elif platform == "soundcloud":
                        # SoundCloud peut avoir thumbnail, artwork_url, ou artwork_url_https
                        thumbnail = data.get('thumbnail') or data.get('artwork_url') or data.get('artwork_url_https') or ""
                    else:
                        thumbnail = data.get('thumbnail') or ""
                    
                    tracks.append({
                        "id": video_id,
                        "title": title,
                        "artist": artist,
                        "duration": data.get('duration', 0),  # May be 0 with --flat-playlist
                        "url": track_url,
                        "thumbnail": thumbnail
                    })
                except (json.JSONDecodeError, KeyError) as e:
                    logger.debug(f"Failed to parse search result: {e}")
                    continue
        
        return {
            "success": True,
            "type": "artist_content",
            "artist": artist_name,
            "content_type": content_type,
            "tracks": tracks,
            "count": len(tracks)
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"Search timeout for artist: {artist_name}")
        raise HTTPException(status_code=504, detail="La recherche a pris trop de temps. Réessayez avec un nom d'artiste plus spécifique.")
    except Exception as e:
        logger.exception(f"Failed to search artist content: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to search: {str(e)}")


@router.post("/queue/extract-album")
async def extract_album_urls(
    request: AlbumExtractRequest,
    user_id: int = Depends(get_current_user_id)
):
    """Extract all URLs from a YouTube Music album/playlist and add to queue"""
    try:
        # Use the search endpoint to get tracks
        search_result = await search_url(request, user_id)
        
        if search_result["type"] != "playlist":
            raise Exception("URL is not a playlist or album")
        
        urls = [track["url"] for track in search_result["tracks"]]
        
        # Add all URLs to queue
        items = queue_manager.add_multiple_to_queue(urls)
        
        return {
            "success": True,
            "message": f"Album extrait: {len(urls)} musiques ajoutées à la queue",
            "queue_size": queue_manager.get_queue_size(),
            "urls_count": len(urls),
            "items": items  # items are already dicts
        }
        
    except Exception as e:
        logger.exception(f"Failed to extract album: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to extract album: {str(e)}")


@router.get("/queue")
async def get_queue(
    user_id: int = Depends(get_current_user_id)
):
    """Get current download queue"""
    return {
        "queue": queue_manager.get_queue(),
        "status": queue_manager.get_status()
    }


@router.delete("/queue/remove")
async def remove_from_queue(
    url: str = Query(..., description="URL to remove from queue"),
    user_id: int = Depends(get_current_user_id)
):
    """Remove URL from queue"""
    success = queue_manager.remove_from_queue(url)
    if success:
        return {
            "success": True,
            "message": "URL retirée de la queue",
            "queue_size": queue_manager.get_queue_size()
        }
    else:
        raise HTTPException(status_code=404, detail="URL not found in queue or already processing")


@router.delete("/queue/clear")
async def clear_queue(
    user_id: int = Depends(get_current_user_id)
):
    """Clear all pending items from queue"""
    try:
        logger.info("Clear queue requested")
        queue_manager.clear_queue()
        queue_size = queue_manager.get_queue_size()
        logger.info(f"Queue cleared successfully, remaining size: {queue_size}")
        return {
            "success": True,
            "message": "Queue vidée",
            "queue_size": queue_size
        }
    except Exception as e:
        logger.exception(f"Error clearing queue: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to clear queue: {str(e)}")


@router.get("/tracks", response_model=List[TrackResponse])
async def list_tracks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    List all tracks in the library
    
    - Supports pagination with skip and limit
    """
    tracks = db.query(Track).offset(skip).limit(limit).all()
    return [TrackResponse.model_validate(track) for track in tracks]


@router.get("/albums")
async def list_albums(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    List all albums grouped by main artist (before comma/feat) and album
    Returns albums with track count
    """
    from sqlalchemy import func
    from app.services.organizer import OrganizerService
    
    organizer = OrganizerService()
    
    # Get all tracks
    tracks = db.query(Track).all()
    
    # Group by main artist and album
    albums_map = {}
    for track in tracks:
        # Extract main artist (before comma/feat) for grouping
        main_artist = organizer._extract_main_artist(track.artist or "Unknown Artist")
        album = track.album or "Unknown Album"
        year = track.year
        
        # Create key for grouping
        key = (main_artist, album, year)
        
        if key not in albums_map:
            albums_map[key] = {
                "artist": main_artist,  # Use main artist for display
                "album": album,
                "year": year,
                "track_count": 0
            }
        
        albums_map[key]["track_count"] += 1
    
    # Convert to list
    result = list(albums_map.values())
    
    # Sort by artist, then album, then year
    result.sort(key=lambda x: (x["artist"], x["album"] or "", x["year"] or 0))
    
    return result


@router.get("/albums/{artist}/{album}/tracks", response_model=List[TrackResponse])
async def get_album_tracks(
    artist: str,
    album: str,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Get all tracks for a specific album
    Uses main artist (before comma/feat) for matching
    """
    from app.services.organizer import OrganizerService
    
    organizer = OrganizerService()
    
    # Get all tracks with matching album
    all_tracks = db.query(Track).filter(
        Track.album == album
    ).all()
    
    # Filter tracks where main artist matches
    matching_tracks = []
    for track in all_tracks:
        main_artist = organizer._extract_main_artist(track.artist or "Unknown Artist")
        if main_artist == artist:
            matching_tracks.append(track)
    
    if not matching_tracks:
        raise HTTPException(status_code=404, detail="Album not found")
    
    return [TrackResponse.model_validate(track) for track in matching_tracks]


@router.get("/tracks/{track_id}", response_model=TrackResponse)
async def get_track(
    track_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Get details of a specific track
    """
    track = db.query(Track).filter(Track.id == track_id).first()
    
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    
    return TrackResponse.model_validate(track)


@router.delete("/tracks/{track_id}")
async def delete_track(
    track_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Delete a track and its file
    
    - Removes track from database
    - Deletes the audio file from filesystem
    """
    track = db.query(Track).filter(Track.id == track_id).first()
    
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found")
    
    # Delete file
    file_path = Path(track.file_path)
    if file_path.exists():
        try:
            file_path.unlink()
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to delete file: {str(e)}"
            )
    
    # Delete from database
    db.delete(track)
    db.commit()
    
    return {"message": f"Track {track_id} deleted successfully"}


@router.get("/search", response_model=List[TrackResponse])
async def search_tracks(
    q: str = Query(..., description="Search query"),
    artist: Optional[str] = Query(None),
    album: Optional[str] = Query(None),
    title: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Search tracks in the library
    
    - General search across all fields if only 'q' is provided
    - Specific field search if artist/album/title are provided
    """
    query = db.query(Track)
    
    # Build search conditions
    conditions = []
    
    if q:
        # General search
        search_term = f"%{q}%"
        conditions.append(
            or_(
                Track.artist.ilike(search_term),
                Track.album.ilike(search_term),
                Track.title.ilike(search_term)
            )
        )
    
    if artist:
        conditions.append(Track.artist.ilike(f"%{artist}%"))
    
    if album:
        conditions.append(Track.album.ilike(f"%{album}%"))
    
    if title:
        conditions.append(Track.title.ilike(f"%{title}%"))
    
    if conditions:
        query = query.filter(or_(*conditions))
    
    tracks = query.all()
    return [TrackResponse.model_validate(track) for track in tracks]


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Get library statistics
    """
    total_tracks = db.query(Track).count()
    total_artists = db.query(Track.artist).distinct().count()
    total_albums = db.query(Track.album).distinct().count()
    
    # Total file size
    total_size = db.query(Track.file_size).filter(Track.file_size.isnot(None)).all()
    total_size_bytes = sum(size[0] for size in total_size if size[0])
    
    return {
        "total_tracks": total_tracks,
        "total_artists": total_artists,
        "total_albums": total_albums,
        "total_size_bytes": total_size_bytes,
        "total_size_gb": round(total_size_bytes / (1024**3), 2) if total_size_bytes else 0
    }


@router.get("/health/diagnostic")
async def diagnostic():
    """
    Diagnostic endpoint to check system configuration
    """
    import subprocess
    import shutil
    
    diagnostics = {
        "tools": {},
        "directories": {},
        "plex": {}
    }
    
    # Check tools
    tools_to_check = {
        "yt-dlp": [YTDLP_CMD, "--version"],
        "spotdl": ["spotdl", "--version"],
        "ffmpeg": ["ffmpeg", "-version"]
    }
    
    for tool_name, cmd in tools_to_check.items():
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=5
            )
            diagnostics["tools"][tool_name] = {
                "installed": result.returncode == 0,
                "version": result.stdout.decode().strip().split('\n')[0] if result.returncode == 0 else None
            }
        except (FileNotFoundError, subprocess.TimeoutExpired):
            diagnostics["tools"][tool_name] = {
                "installed": False,
                "version": None
            }
    
    # Check directories
    directories_to_check = {
        "music": settings.MUSIC_DIR,
        "downloads": settings.DOWNLOADS_DIR,
        "config": settings.CONFIG_DIR
    }
    
    for dir_name, dir_path in directories_to_check.items():
        diagnostics["directories"][dir_name] = {
            "exists": dir_path.exists(),
            "writable": os.access(dir_path, os.W_OK) if dir_path.exists() else False,
            "path": str(dir_path)
        }
    
    # Check Plex configuration
    diagnostics["plex"] = {
        "server_url": settings.PLEX_SERVER_URL,
        "token_configured": settings.PLEX_TOKEN is not None,
        "library_id": settings.PLEX_LIBRARY_SECTION_ID,
        "auto_scan": settings.PLEX_AUTO_SCAN,
        "configured": plex_service.is_configured()
    }
    
    return diagnostics


@router.post("/api/music/fix-plex-metadata", response_model=dict)
async def fix_plex_metadata(
    dry_run: bool = Query(False, description="Mode simulation sans modification"),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Corriger les métadonnées pour Plex
    
    Cette route permet de :
    - Mettre à jour les métadonnées dans les fichiers pour correspondre à la structure
    - Forcer un refresh complet de Plex
    - Vider la corbeille Plex
    
    Args:
        dry_run: Si True, simule sans modifier les fichiers
    
    Returns:
        Statistiques de la correction
    """
    try:
        from app.services.plex_metadata_fixer import PlexMetadataFixer
        
        logger.info(f"🔧 Démarrage de la correction des métadonnées Plex (dry_run={dry_run})")
        fixer = PlexMetadataFixer()
        stats = fixer.fix_all_metadata(dry_run=dry_run)
        
        # Forcer le refresh complet de Plex
        if not dry_run and stats['fixed'] > 0:
            logger.info("🔄 Refresh complet de Plex...")
            plex_service.empty_trash()
            plex_service.force_refresh_metadata()
        
        return {
            "success": True,
            "stats": stats,
            "message": f"Correction terminée: {stats['fixed']}/{stats['total_files']} fichiers corrigés"
        }
    except Exception as e:
        logger.error(f"Erreur lors de la correction: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/music/cleanup-artists", response_model=dict)
async def cleanup_artists(
    dry_run: bool = Query(False, description="Mode simulation sans modification"),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Nettoyer et fusionner les artistes en double
    
    Cette route permet de :
    - Fusionner les artistes en double (ex: "Sofiane Officiel" → "Sofiane")
    - Corriger les noms d'artistes (ex: "B20baOfficiel" → "Booba")
    - Traiter les fichiers dans "Unknown Artist"
    - Réorganiser la bibliothèque
    
    Args:
        dry_run: Si True, simule sans modifier les fichiers
    
    Returns:
        Statistiques du nettoyage
    """
    try:
        logger.info(f"🎨 Démarrage du nettoyage des artistes (dry_run={dry_run})")
        cleanup_service = ArtistCleanupService()
        stats = cleanup_service.clean_all_artists(dry_run=dry_run)
        
        # Recharger Plex si des fichiers ont été déplacés
        if not dry_run and stats['files_moved'] > 0:
            plex_service.force_refresh_metadata()
        
        return {
            "success": True,
            "stats": stats,
            "message": f"Nettoyage terminé: {stats['artists_merged']} artistes fusionnés, {stats['files_moved']} fichiers déplacés"
        }
    except Exception as e:
        logger.error(f"Erreur lors du nettoyage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/music/sort", response_model=dict)
async def sort_music_library(
    dry_run: bool = Query(False, description="Mode simulation sans modification"),
    user_id: Optional[int] = Depends(get_current_user_id)
):
    """
    Trier et enrichir toute la bibliothèque musicale
    
    Cette route permet de :
    - Enrichir les métadonnées via MusicBrainz
    - Nettoyer les noms de fichiers (enlever "(Official Video)", URLs, etc.)
    - Réorganiser les fichiers selon la structure Plex
    - Télécharger et intégrer les pochettes d'album
    - Recharger la bibliothèque Plex
    
    Args:
        dry_run: Si True, simule sans modifier les fichiers
    
    Returns:
        Statistiques du tri
    """
    try:
        logger.info(f"🎵 Démarrage du tri de la bibliothèque (dry_run={dry_run})")
        sorter = MusicSorterService()
        stats = sorter.sort_all_music(dry_run=dry_run)
        return {
            "success": True,
            "stats": stats,
            "message": f"Tri terminé: {stats['processed']}/{stats['total_files']} fichiers traités"
        }
    except Exception as e:
        logger.error(f"Erreur lors du tri: {e}")
        raise HTTPException(status_code=500, detail=str(e))

