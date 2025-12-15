"""Utility functions for downloaders"""
import subprocess
import re
import time
import fcntl
import shutil
import logging
from pathlib import Path
from typing import Optional
from app.config import settings

logger = logging.getLogger(__name__)


def get_ffmpeg_path() -> Optional[str]:
    """Get ffmpeg executable path"""
    spotdl_dir = Path.home() / ".spotdl"
    if (spotdl_dir / "ffmpeg").exists():
        return str(spotdl_dir / "ffmpeg")
    return shutil.which("ffmpeg")


def find_downloaded_file(directory: Path) -> Optional[Path]:
    """Find the most recently downloaded file in directory"""
    # Chercher d'abord les formats audio courants (flac en priorité maintenant)
    audio_extensions = ["flac", "m4a", "opus", "mp3", "webm", "ogg", "aac", "wav"]
    
    # Get all audio files (exclude .webp thumbnails, .lock files, and .temp.m4a)
    audio_files = []
    for ext in audio_extensions:
        files = [f for f in directory.glob(f"*.{ext}") 
                 if f.suffix.lower() == f".{ext}" 
                 and not f.name.endswith('.lock')
                 and not f.name.endswith('.temp.m4a')]  # Exclure .temp.m4a
        audio_files.extend(files)
    
    # Chercher aussi les fichiers .temp.m4a qui sont en cours de téléchargement
    temp_files = [f for f in directory.glob("*.temp.m4a") if f.is_file()]
    
    # Si on trouve des fichiers .temp.m4a, attendre qu'ils soient renommés
    if temp_files:
        logger.info(f"Found {len(temp_files)} .temp.m4a file(s), waiting for rename...")
        for _ in range(20):  # Attendre jusqu'à 10 secondes
            time.sleep(0.5)
            # Vérifier si un fichier .m4a correspondant existe maintenant
            for temp_file in temp_files:
                # Le fichier .temp.m4a devrait être renommé en .m4a
                m4a_file = temp_file.with_suffix('').with_suffix('.m4a')
                if m4a_file.exists():
                    logger.info(f"Temp file renamed: {temp_file.name} -> {m4a_file.name}")
                    audio_files.append(m4a_file)
                    break
            if audio_files:
                break
        # Si après 10s le fichier n'est toujours pas renommé, utiliser le .temp
        if not audio_files and temp_files:
            logger.warning(f"Temp file not renamed after 10s, using it anyway: {temp_files[0].name}")
            # Renommer manuellement le fichier .temp.m4a en .m4a
            temp_file = temp_files[0]
            m4a_file = temp_file.with_suffix('').with_suffix('.m4a')
            try:
                temp_file.rename(m4a_file)
                logger.info(f"Manually renamed temp file: {temp_file.name} -> {m4a_file.name}")
                audio_files.append(m4a_file)
            except Exception as e:
                logger.warning(f"Could not rename temp file: {e}, using temp file")
                audio_files.append(temp_file)
    
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
            audio_file = extract_audio_from_video(mp4_file)
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


def extract_audio_from_video(video_file: Path) -> Optional[Path]:
    """Extract audio from a video file using ffmpeg"""
    try:
        ffmpeg_path = get_ffmpeg_path()
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


def extract_base_flac_name(flac_name: str) -> str:
    """
    Extract base FLAC name without timestamp/hash suffix
    Format: "Title_timestamp_hash.flac" -> "Title.flac"
    """
    # Pattern: Title_timestamp_hash.flac
    base_name_match = re.match(r'^(.+?)_\d+_[a-f0-9]+\.flac$', flac_name)
    if base_name_match:
        return base_name_match.group(1) + ".flac"
    return flac_name


def find_flac_in_music(flac_name: str, music_dir: Path) -> Optional[Path]:
    """
    Find FLAC file in music directory by name (with or without suffix)
    Returns the first matching file found, or None
    """
    base_flac_name = extract_base_flac_name(flac_name)
    logger.info(f"🔍 Searching for FLAC in music/: original='{flac_name}', base='{base_flac_name}'")
    
    # Chercher avec le nom de base ET le nom complet
    found_files = []
    search_count = 0
    for flac_in_music in music_dir.rglob("*.flac"):
        search_count += 1
        if flac_in_music.name == base_flac_name or flac_in_music.name == flac_name:
            if flac_in_music.exists() and flac_in_music.stat().st_size > 0:
                logger.info(f"✅ Found matching FLAC: {flac_in_music} (name: {flac_in_music.name})")
                found_files.append(flac_in_music)
    
    if found_files:
        logger.info(f"✅ Found {len(found_files)} matching FLAC file(s) in music/")
        # Retourner le premier fichier trouvé
        return found_files[0]
    
    logger.warning(f"❌ No matching FLAC found in music/ for '{flac_name}' or '{base_flac_name}' (searched {search_count} files)")
    return None


def convert_to_flac_with_thumbnail(m4a_file: Path, thumbnail_url: Optional[str] = None) -> Path:
    """Convert m4a file to FLAC and embed thumbnail webp"""
    try:
        if not m4a_file.exists():
            logger.error(f"m4a file does not exist: {m4a_file}")
            return m4a_file
        
        # Find ffmpeg
        ffmpeg_path = get_ffmpeg_path()
        if not ffmpeg_path:
            logger.error("ffmpeg not found, cannot convert to FLAC")
            raise Exception("ffmpeg not found")
        
        logger.info(f"Using ffmpeg: {ffmpeg_path}")
        
        # Output FLAC file (same directory as m4a)
        flac_file = m4a_file.parent / f"{m4a_file.stem}.flac"
        
        # 1. Vérifier si le FLAC existe déjà (créé par un autre processus)
        if flac_file.exists() and flac_file.stat().st_size > 0:
            logger.info(f"FLAC file already exists, skipping conversion: {flac_file}")
            return flac_file
        
        # Vérifier aussi dans le dossier music si le FLAC existe déjà (peut avoir été déplacé)
        music_dir = settings.MUSIC_DIR
        flac_name = flac_file.name
        
        # Chercher récursivement dans music/ pour voir si le fichier a été déplacé
        flac_in_music = find_flac_in_music(flac_name, music_dir)
        if flac_in_music:
            logger.info(f"FLAC file already exists in music directory (was moved): {flac_in_music}")
            # Si le fichier existe aussi dans downloads/, retourner celui-là
            if flac_file.exists() and flac_file.stat().st_size > 0:
                return flac_file
            # Sinon, retourner celui de music/
            return flac_in_music
        
        # 2. Vérifier que le fichier m4a existe encore
        if not m4a_file.exists():
            # Vérifier si un fichier .temp.m4a correspondant existe
            temp_m4a = m4a_file.with_suffix('.temp.m4a')
            if temp_m4a.exists():
                logger.info(f"Found .temp.m4a file, waiting for rename: {temp_m4a.name}")
                for _ in range(20):  # Attendre jusqu'à 10 secondes
                    time.sleep(0.5)
                    if m4a_file.exists():
                        logger.info(f"Temp file renamed: {temp_m4a.name} -> {m4a_file.name}")
                        break
                else:
                    # Si après 10s le fichier n'est toujours pas renommé, renommer manuellement
                    logger.warning(f"Temp file not renamed after 10s, renaming manually")
                    try:
                        temp_m4a.rename(m4a_file)
                        logger.info(f"Manually renamed: {temp_m4a.name} -> {m4a_file.name}")
                    except Exception as e:
                        logger.warning(f"Could not rename temp file: {e}")
                        raise Exception(f"M4A file was not found and temp file could not be renamed: {m4a_file}")
            else:
                logger.warning(f"M4A file no longer exists: {m4a_file}, may have been processed by another worker")
                raise Exception(f"M4A file was already processed: {m4a_file}")
        
        # 3. Utiliser un lock fichier pour éviter les conversions simultanées
        lock_file_path = m4a_file.with_suffix('.lock')
        lock_file = None
        
        try:
            # Créer le fichier de lock
            lock_file_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = open(lock_file_path, 'w')
            
            # Acquérir le lock (non-bloquant)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                logger.info(f"Lock acquired for conversion: {m4a_file.name}")
            except BlockingIOError:
                # Un autre processus convertit déjà, attendre qu'il finisse
                logger.info(f"Another process is converting {m4a_file.name}, waiting...")
                lock_file.close()
                lock_file = None
                
                # Attendre jusqu'à 30 secondes que le FLAC soit créé
                music_dir = settings.MUSIC_DIR
                flac_name = flac_file.name
                
                for i in range(60):  # 60 * 0.5s = 30s max
                    time.sleep(0.5)
                    
                    # Vérifier dans downloads/
                    if flac_file.exists() and flac_file.stat().st_size > 0:
                        logger.info(f"FLAC file created by another process: {flac_file}")
                        return flac_file
                    
                    # Vérifier aussi dans music/ (peut avoir été déplacé)
                    flac_in_music = find_flac_in_music(flac_name, music_dir)
                    if flac_in_music:
                        logger.info(f"FLAC file found in music directory (was moved by another process): {flac_in_music}")
                        # Si le fichier existe aussi dans downloads/, retourner celui-là
                        if flac_file.exists() and flac_file.stat().st_size > 0:
                            return flac_file
                        # Sinon, retourner celui de music/
                        return flac_in_music
                    
                    # Réessayer d'acquérir le lock toutes les 5 secondes
                    if i % 10 == 0 and i > 0:
                        try:
                            lock_file = open(lock_file_path, 'w')
                            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                            logger.info(f"Lock acquired after waiting: {m4a_file.name}")
                            # Vérifier à nouveau dans music/ maintenant qu'on a le lock
                            flac_in_music = find_flac_in_music(flac_name, music_dir)
                            if flac_in_music:
                                logger.info(f"FLAC file found in music directory after acquiring lock: {flac_in_music}")
                                return flac_in_music
                            # Vérifier aussi dans downloads/
                            if flac_file.exists() and flac_file.stat().st_size > 0:
                                logger.info(f"FLAC file found in downloads after acquiring lock: {flac_file}")
                                return flac_file
                            break  # Lock acquis, on peut continuer
                        except BlockingIOError:
                            continue
                
                # Si après 30s le FLAC n'existe toujours pas, vérifier une dernière fois dans music/
                if not flac_file.exists():
                    flac_in_music = find_flac_in_music(flac_name, music_dir)
                    if flac_in_music:
                        logger.info(f"FLAC file found in music directory after timeout: {flac_in_music}")
                        return flac_in_music
                    raise Exception(f"FLAC file was not created after waiting 30s: {m4a_file.name}")
                return flac_file
            
            # Vérifier à nouveau que le m4a existe (peut avoir été supprimé pendant l'attente)
            if not m4a_file.exists():
                # Vérifier si le FLAC existe dans music/ (peut avoir été déplacé)
                flac_in_music = find_flac_in_music(flac_name, music_dir)
                if flac_in_music:
                    logger.info(f"M4A was removed but FLAC exists in music directory: {flac_in_music}")
                    return flac_in_music
                raise Exception(f"M4A file was removed while waiting for lock: {m4a_file}")
            
            # Vérifier à nouveau que le FLAC n'existe pas dans downloads/
            if flac_file.exists() and flac_file.stat().st_size > 0:
                logger.info(f"FLAC file created by another process while waiting: {flac_file}")
                return flac_file
            
            # Vérifier aussi dans music/ (peut avoir été déplacé pendant l'attente)
            flac_in_music = find_flac_in_music(flac_name, music_dir)
            if flac_in_music:
                logger.info(f"FLAC file found in music directory (was moved while waiting for lock): {flac_in_music}")
                # Si le fichier existe aussi dans downloads/, retourner celui-là
                if flac_file.exists() and flac_file.stat().st_size > 0:
                    return flac_file
                # Sinon, retourner celui de music/
                return flac_in_music
            
            # Dernière vérification avant de commencer la conversion
            # (le fichier peut avoir été créé et déplacé pendant qu'on vérifiait le m4a)
            if not flac_file.exists() or (flac_file.exists() and flac_file.stat().st_size == 0):
                flac_in_music = find_flac_in_music(flac_name, music_dir)
                if flac_in_music:
                    logger.info(f"FLAC file found in music directory (final check before conversion): {flac_in_music}")
                    return flac_in_music
            
            logger.info(f"Converting {m4a_file} to {flac_file}")
            
            # Attendre que le fichier soit complètement téléchargé
            # Vérifier que la taille du fichier est stable (pas en cours d'écriture)
            max_wait = 10  # Maximum 10 secondes d'attente
            wait_interval = 0.5  # Vérifier toutes les 0.5 secondes
            waited = 0
            
            previous_size = 0
            stable_count = 0
            required_stable_checks = 3  # Le fichier doit être stable pendant 3 vérifications
            
            logger.info(f"Waiting for file to be completely downloaded: {m4a_file.name}")
            while waited < max_wait:
                current_size = m4a_file.stat().st_size
                
                if current_size == previous_size:
                    stable_count += 1
                    if stable_count >= required_stable_checks:
                        logger.info(f"File size stable at {current_size} bytes after {waited:.1f}s")
                        break
                else:
                    stable_count = 0
                    previous_size = current_size
                
                time.sleep(wait_interval)
                waited += wait_interval
            
            file_size = m4a_file.stat().st_size
            if file_size == 0:
                raise Exception(f"M4A file is empty (0 bytes): {m4a_file}")
            
            # Taille minimale pour un fichier audio valide (environ 1 KB)
            if file_size < 1024:
                raise Exception(f"M4A file is too small ({file_size} bytes), likely corrupted: {m4a_file}")
            
            logger.info(f"M4A file size: {file_size} bytes")
            
            # Vérifier que le fichier m4a est valide (moov atom présent)
            # Utiliser ffprobe pour vérifier la validité du fichier
            ffprobe_path = shutil.which("ffprobe")
            if ffprobe_path:
                try:
                    probe_cmd = [
                        ffprobe_path,
                        "-v", "error",
                        "-show_entries", "format=duration",
                        "-of", "default=noprint_wrappers=1:nokey=1",
                        str(m4a_file)
                    ]
                    probe_result = subprocess.run(
                        probe_cmd,
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if probe_result.returncode != 0:
                        error_msg = probe_result.stderr.strip()
                        if "moov atom not found" in error_msg.lower() or "invalid data" in error_msg.lower():
                            raise Exception(f"M4A file is incomplete or corrupted (moov atom not found): {m4a_file}. Error: {error_msg}")
                        logger.warning(f"ffprobe warning for {m4a_file.name}: {error_msg}")
                    else:
                        duration = probe_result.stdout.strip()
                        if duration:
                            logger.info(f"M4A file is valid, duration: {duration}s")
                        else:
                            logger.warning(f"ffprobe returned no duration for {m4a_file.name}")
                except subprocess.TimeoutExpired:
                    logger.warning(f"ffprobe timeout for {m4a_file.name}, skipping validation")
                except Exception as e:
                    logger.warning(f"Could not validate m4a file with ffprobe: {e}, proceeding anyway")
            else:
                logger.warning("ffprobe not found, skipping m4a validation")
            
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
                "-loglevel", "error",  # Réduire les logs verbeux
                str(flac_file)
            ]
            
            logger.info(f"Step 1: Converting audio to FLAC...")
            logger.info(f"ffmpeg command: {' '.join(cmd)}")
            
            # Exécuter ffmpeg avec meilleure gestion des erreurs
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False  # Ne pas lever d'exception automatiquement
                )
            except subprocess.TimeoutExpired:
                raise Exception(f"ffmpeg conversion timeout after 120 seconds for {m4a_file.name}")
            except Exception as e:
                raise Exception(f"ffmpeg execution error: {str(e)}")
            
            if result.returncode != 0:
                # Extraire le vrai message d'erreur
                error_msg = result.stderr.strip() if result.stderr else result.stdout.strip() if result.stdout else "Unknown error"
                
                # Si le message d'erreur ne contient que la version, essayer de trouver le vrai problème
                if "ffmpeg version" in error_msg and len(error_msg) < 200:
                    # Le vrai message d'erreur pourrait être dans stdout
                    if result.stdout:
                        error_msg = result.stdout.strip()
                
                logger.error(f"ffmpeg audio conversion failed (returncode: {result.returncode})")
                logger.error(f"ffmpeg stderr (full): {result.stderr}")
                logger.error(f"ffmpeg stdout (full): {result.stdout}")
                
                # Vérifier si le fichier de sortie existe malgré l'erreur
                if flac_file.exists() and flac_file.stat().st_size > 0:
                    logger.warning(f"FLAC file was created despite error code {result.returncode}, using it")
                else:
                    raise Exception(f"FLAC audio conversion failed (code {result.returncode}): {error_msg}")
            
            if not flac_file.exists():
                # Vérifier dans music/ avant de lever l'exception (peut avoir été déplacé)
                logger.warning(f"FLAC file not found in downloads: {flac_file.name}, checking music directory...")
                # S'assurer que flac_name et music_dir sont définis
                if 'flac_name' not in locals():
                    flac_name = flac_file.name
                if 'music_dir' not in locals():
                    music_dir = settings.MUSIC_DIR
                flac_in_music = find_flac_in_music(flac_name, music_dir)
                if flac_in_music:
                    logger.info(f"FLAC file found in music directory (was moved after conversion): {flac_in_music}")
                    return flac_in_music
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
        finally:
            # Libérer le lock fichier
            if lock_file:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    lock_file.close()
                    logger.debug(f"Lock released for: {m4a_file.name}")
                except Exception as e:
                    logger.warning(f"Error releasing lock: {e}")
            # Supprimer le fichier de lock
            try:
                if lock_file_path.exists():
                    lock_file_path.unlink()
            except Exception as e:
                logger.warning(f"Error removing lock file: {e}")
    
    except Exception as e:
        logger.error(f"Error in convert_to_flac_with_thumbnail: {e}")
        raise
