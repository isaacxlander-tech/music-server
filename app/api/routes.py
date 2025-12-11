"""API routes for music server"""
import logging
import os
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
from app.services.task_manager import task_manager, TaskStatus
from app.services.queue_manager import get_queue_manager
from app.api.auth import get_current_user_id
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

downloader_service = DownloaderService()
metadata_service = MetadataService()
organizer_service = OrganizerService()
plex_service = PlexService()
queue_manager = get_queue_manager(task_manager)


def process_download_sync(task_id: str, url: str, source: Optional[SourceType]):
    """Synchronous background task to process download (for thread pool execution)"""
    db = SessionLocal()
    try:
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 5, "Préparation du téléchargement...")
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 15, "Téléchargement en cours...")
        
        # Download file (maintenant beaucoup plus rapide - télécharge directement le meilleur format)
        file_path, download_metadata, detected_source = downloader_service.download(
            url,
            source
        )
        
        if file_path is None:
            raise Exception("Download completed but file not found")
        
        task_manager.update_task(task_id, TaskStatus.DOWNLOADING, 50, "Téléchargement terminé, conversion en FLAC...")
        logger.info(f"File downloaded to: {file_path}")
        logger.info(f"Download metadata from YouTube: {download_metadata}")
        
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
        
        # Extract metadata from downloaded file
        file_metadata = metadata_service.extract_metadata(file_path)
        logger.info(f"Metadata extracted from file: {file_metadata}")
        
        task_manager.update_task(task_id, TaskStatus.PROCESSING, 60, "Organisation du fichier...")
        
        # Merge with download metadata (from yt-dlp)
        if download_metadata:
            # Prioritize download metadata over file metadata (more accurate from YouTube)
            if download_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("artist")
            elif download_metadata.get("uploader") and not file_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("uploader")
            elif download_metadata.get("channel") and not file_metadata.get("artist"):
                file_metadata["artist"] = download_metadata.get("channel")
            
            if download_metadata.get("title") and not file_metadata.get("title"):
                file_metadata["title"] = download_metadata.get("title")
            
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
        
    except Exception as e:
        logger.exception(f"Error in download task {task_id}: {str(e)}")
        task_manager.update_task(task_id, error=str(e))
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
        item = queue_manager.add_to_queue(request.url, request.source)
        
        return {
            "success": True,
            "message": "Ajouté à la queue de téléchargement",
            "queue_size": queue_manager.get_queue_size(),
            "item": item.to_dict()
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
        item = queue_manager.add_to_queue(request.url, request.source)
        return {
            "success": True,
            "message": "URL ajoutée à la queue",
            "queue_size": queue_manager.get_queue_size(),
            "item": item.to_dict()
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
        items = queue_manager.add_multiple_to_queue(request.urls, request.source)
        return {
            "success": True,
            "message": f"{len(request.urls)} URLs ajoutées à la queue",
            "queue_size": queue_manager.get_queue_size(),
            "items": [item.to_dict() for item in items]
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
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                "--cookies-from-browser", "chrome",
                url
            ]
            
            logger.info(f"Extracting playlist, timeout: 120s")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120  # 2 minutes for playlists
                )
            except subprocess.TimeoutExpired:
                logger.error("Playlist extraction timed out after 120 seconds")
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
                        "yt-dlp",
                        "--dump-json",
                        "--no-warnings",
                        "--cookies-from-browser", "chrome",
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
                "yt-dlp",
                "--dump-json",
                "--no-warnings",
                "--cookies-from-browser", "chrome",
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
        limit = request.get("limit", 20)  # More results for better artist grouping
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Fast search with minimal metadata
        search_query = f"ytsearch{limit}:{query}"
        
        cmd = [
            "yt-dlp",
            "--flat-playlist",  # Faster, no full metadata
            "--dump-json",
            "--no-warnings",
            "--no-playlist",  # Don't extract playlists
            "--cookies-from-browser", "chrome",
            search_query
        ]
        
        logger.info(f"Fast search for: {query}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15  # Shorter timeout for quick search
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
                    video_id = data.get('id', '')
                    if not video_id:
                        continue
                    
                    # Extract artist from title or channel
                    title = data.get('title', 'Unknown')
                    artist = data.get('uploader') or data.get('channel') or 'Unknown Artist'
                    
                    # Construct URL
                    track_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    # Group by artist
                    if artist not in artists_map:
                        artists_map[artist] = {
                            "name": artist,
                            "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg",
                            "tracks": []
                        }
                    
                    artists_map[artist]["tracks"].append({
                        "id": video_id,
                        "title": title,
                        "url": track_url,
                        "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
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
        result_type = request.get("type", "songs")  # songs, albums, playlists
        limit = request.get("limit", 10)
        
        if not query:
            raise HTTPException(status_code=400, detail="Query is required")
        
        # Use ytsearch: prefix for YouTube search
        search_query = f"ytsearch{limit}:{query}"
        
        cmd = [
            "yt-dlp",
            "--dump-json",
            "--no-warnings",
            "--cookies-from-browser", "chrome",
            search_query
        ]
        
        logger.info(f"Searching YouTube for: {query} (type: {result_type})")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
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
                    video_id = data.get('id', '')
                    if not video_id:
                        continue
                    
                    # Construct URL
                    track_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    tracks.append({
                        "id": video_id,
                        "title": data.get('title', 'Unknown'),
                        "artist": data.get('uploader') or data.get('channel', 'Unknown Artist'),
                        "duration": data.get('duration', 0),
                        "url": track_url,
                        "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
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
        content_type = request.get("type", "songs")  # songs, albums, playlists
        limit = request.get("limit", 20)
        
        if not artist_name:
            raise HTTPException(status_code=400, detail="Artist name is required")
        
        # Fast search with --flat-playlist (no full metadata extraction)
        search_query = f"ytsearch{limit}:{artist_name}"
        
        cmd = [
            "yt-dlp",
            "--flat-playlist",  # Faster - no full metadata
            "--dump-json",
            "--no-warnings",
            "--no-playlist",
            "--cookies-from-browser", "chrome",
            search_query
        ]
        
        logger.info(f"Fast search content for artist: {artist_name} (type: {content_type})")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15  # Reduced timeout for faster response
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
                    video_id = data.get('id', '')
                    if not video_id:
                        continue
                    
                    # Extract artist from title or channel
                    title = data.get('title', 'Unknown')
                    artist = data.get('uploader') or data.get('channel') or 'Unknown Artist'
                    
                    # Filter by artist if needed (case-insensitive partial match)
                    if artist_name.lower() not in artist.lower() and artist.lower() not in artist_name.lower():
                        continue
                    
                    track_url = f"https://www.youtube.com/watch?v={video_id}"
                    
                    tracks.append({
                        "id": video_id,
                        "title": title,
                        "artist": artist,
                        "duration": data.get('duration', 0),  # May be 0 with --flat-playlist
                        "url": track_url,
                        "thumbnail": data.get('thumbnail') or f"https://i.ytimg.com/vi/{video_id}/default.jpg"
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
            "items": [item.to_dict() for item in items]
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
    queue_manager.clear_queue()
    return {
        "success": True,
        "message": "Queue vidée",
        "queue_size": queue_manager.get_queue_size()
    }


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
        "yt-dlp": ["yt-dlp", "--version"],
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

