"""Service de tri et enrichissement des métadonnées musicales"""
import logging
import re
import requests
import time
from pathlib import Path
from typing import Optional, Dict, Any, List
from mutagen.flac import FLAC, Picture
from mutagen import File
from app.config import settings
from app.services.metadata import MetadataService
from app.services.organizer import OrganizerService
from app.services.plex import PlexService

logger = logging.getLogger(__name__)


class MusicSorterService:
    """Service pour trier et enrichir les métadonnées de la bibliothèque musicale"""
    
    def __init__(self):
        self.music_dir = settings.MUSIC_DIR
        self.metadata_service = MetadataService()
        self.organizer_service = OrganizerService()
        self.plex_service = PlexService()
        self.musicbrainz_base_url = "https://musicbrainz.org/ws/2"
        self.cover_art_base_url = "https://coverartarchive.org"
        self.rate_limit_delay = 1.0  # Délai entre les requêtes (MusicBrainz limite à 1 req/sec)
        
        # Patterns pour nettoyer les noms de fichiers
        self.cleanup_patterns = [
            r'\s*\([Ll]yrics?\s*[Vv]ideo?\)',
            r'\s*\([Ll]yrics?\)',  # Pattern spécifique pour "(Lyrics)"
            r'\s*\([Oo]fficial\s+[Vv]ideo?\)',
            r'\s*\([Oo]fficial\s+[Mm]usic\s+[Vv]ideo?\)',
            r'\s*\([Oo]fficial\s+[Aa]udio\)',
            r'\s*\([Cc]lip\s+[Oo]fficiel\)',
            r'\s*\([Vv]isualizer\)',
            r'\s*\([Pp]rod\.\s+[Bb]y\s+[^)]+\)',
            r'\s*\[[Cc]lip\s+[Oo]fficiel\]',
            r'\s*\[[Oo]fficial\s+[Vv]ideo?\]',
            r'\s*\[[Oo]fficial\s+[Aa]udio\]',
            r'\s*\[[Ll]yrics?\s*[Vv]ideo?\]',
            r'\s*\[[Ll]yrics?\]',  # Pattern spécifique pour "[Lyrics]"
            r'\s*feat\.\s+[^-]+(?=\s*-|\s*$)',  # Enlever "feat. Artist" mais garder le titre après "-"
            r'\s*ft\.\s+[^-]+(?=\s*-|\s*$)',  # Enlever "ft. Artist" mais garder le titre après "-"
            r'\s*x\s+[^-]+(?=\s*-|\s*$)',  # Enlever "x Artist" mais garder le titre après "-"
            r'\s*-\s*[Oo]fficial.*$',  # Enlever "- Official..." à la fin
            r'\s*-\s*[Cc]lip.*$',
            r'\s*-\s*[Ll]yrics?.*$',
            r'https?://[^\s]+',  # Enlever les URLs
            r'www\.[^\s]+',
        ]
    
    def sort_all_music(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Trier et enrichir toute la bibliothèque musicale
        
        Args:
            dry_run: Si True, ne fait que simuler sans modifier les fichiers
        
        Returns:
            Statistiques du tri
        """
        logger.info("🎵 Démarrage du tri de la bibliothèque musicale...")
        
        stats = {
            "total_files": 0,
            "processed": 0,
            "enriched": 0,
            "reorganized": 0,
            "errors": 0,
            "skipped": 0
        }
        
        # Récupérer tous les fichiers audio
        audio_files = self._get_all_audio_files()
        stats["total_files"] = len(audio_files)
        
        logger.info(f"📁 {stats['total_files']} fichiers audio trouvés")
        
        for file_path in audio_files:
            try:
                logger.info(f"\n📄 Traitement: {file_path.name}")
                
                # Extraire les métadonnées actuelles
                current_metadata = self.metadata_service.extract_metadata(file_path)
                
                # Nettoyer le titre du fichier
                cleaned_title = self._clean_filename_title(
                    current_metadata.get("title") or file_path.stem
                )
                
                # Enrichir les métadonnées via MusicBrainz
                enriched_metadata = self._enrich_metadata(
                    current_metadata.get("artist"),
                    cleaned_title,
                    current_metadata.get("album")
                )
                
                # Fusionner les métadonnées (priorité à l'enrichissement)
                final_metadata = self._merge_metadata(current_metadata, enriched_metadata)
                
                # Nettoyer les métadonnées
                final_metadata["title"] = cleaned_title
                final_metadata = self._clean_metadata(final_metadata)
                
                if enriched_metadata:
                    stats["enriched"] += 1
                    logger.info(f"✅ Métadonnées enrichies: {final_metadata.get('artist')} - {final_metadata.get('title')} ({final_metadata.get('album')})")
                
                if not dry_run:
                    # Mettre à jour les métadonnées dans le fichier
                    self.metadata_service.update_metadata(
                        file_path,
                        artist=final_metadata.get("artist"),
                        album=final_metadata.get("album"),
                        title=final_metadata.get("title"),
                        year=final_metadata.get("year"),
                        genre=final_metadata.get("genre")
                    )
                    
                    # Télécharger la pochette si disponible
                    if enriched_metadata and enriched_metadata.get("cover_art_url"):
                        self._download_cover_art(file_path, enriched_metadata["cover_art_url"])
                    
                    # Réorganiser le fichier si nécessaire
                    new_path = self._reorganize_file(file_path, final_metadata)
                    if new_path != file_path:
                        stats["reorganized"] += 1
                        file_path = new_path
                
                stats["processed"] += 1
                
                # Respecter le rate limit de MusicBrainz
                time.sleep(self.rate_limit_delay)
                
            except Exception as e:
                logger.error(f"❌ Erreur lors du traitement de {file_path}: {e}")
                stats["errors"] += 1
                continue
        
        logger.info(f"\n✅ Tri terminé: {stats['processed']}/{stats['total_files']} fichiers traités")
        logger.info(f"   - Enrichis: {stats['enriched']}")
        logger.info(f"   - Réorganisés: {stats['reorganized']}")
        logger.info(f"   - Erreurs: {stats['errors']}")
        
        # Recharger Plex si configuré
        if not dry_run and stats["reorganized"] > 0:
            logger.info("🔄 Rechargement de la bibliothèque Plex...")
            self.plex_service.scan_library()
        
        return stats
    
    def _get_all_audio_files(self) -> List[Path]:
        """Récupérer tous les fichiers audio du dossier music"""
        audio_extensions = ['.flac', '.mp3', '.m4a', '.opus', '.ogg', '.wav']
        audio_files = []
        
        for ext in audio_extensions:
            audio_files.extend(self.music_dir.rglob(f"*{ext}"))
        
        return sorted(audio_files)
    
    def _enrich_metadata(
        self,
        artist: Optional[str],
        title: Optional[str],
        album: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Enrichir les métadonnées via l'API MusicBrainz
        
        Args:
            artist: Nom de l'artiste
            title: Titre de la chanson
            album: Nom de l'album (optionnel)
        
        Returns:
            Dictionnaire de métadonnées enrichies ou None
        """
        if not artist or not title:
            return None
        
        # Ignorer les artistes inconnus
        if artist.lower() in ["unknown artist", "unknown", ""]:
            return None
        
        try:
            # Rechercher l'enregistrement (recording) sur MusicBrainz
            recording = self._search_recording(artist, title)
            
            if not recording:
                logger.debug(f"Aucun enregistrement trouvé pour {artist} - {title}")
                return None
            
            # Récupérer les détails de l'enregistrement
            recording_id = recording.get("id")
            if not recording_id:
                return None
            
            # Récupérer les informations complètes
            recording_details = self._get_recording_details(recording_id)
            
            if not recording_details:
                return None
            
            # Extraire les métadonnées
            metadata = {
                "artist": self._extract_artist_from_recording(recording_details),
                "title": recording_details.get("title", title),
                "album": self._extract_album_from_recording(recording_details),
                "year": self._extract_year_from_recording(recording_details),
                "genre": self._extract_genre_from_recording(recording_details),
                "cover_art_url": self._get_cover_art_url(recording_details)
            }
            
            return metadata
            
        except Exception as e:
            logger.warning(f"Erreur lors de l'enrichissement via MusicBrainz: {e}")
            return None
    
    def _search_recording(self, artist: str, title: str) -> Optional[Dict]:
        """Rechercher un enregistrement sur MusicBrainz"""
        try:
            # Nettoyer le titre pour la recherche
            search_title = re.sub(r'[^\w\s]', ' ', title).strip()
            search_artist = re.sub(r'[^\w\s]', ' ', artist).strip()
            
            # Enlever les caractères spéciaux qui peuvent poser problème
            search_title = search_title.replace('"', '').replace("'", "")
            search_artist = search_artist.replace('"', '').replace("'", "")
            
            # Construire la requête de recherche
            query = f'recording:"{search_title}" AND artist:"{search_artist}"'
            
            url = f"{self.musicbrainz_base_url}/recording"
            params = {
                "query": query,
                "limit": 1,
                "fmt": "json"
            }
            
            headers = {
                "User-Agent": "MusicHome/1.0 (https://github.com/your-repo)",
                "Accept": "application/json"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                recordings = data.get("recordings", [])
                if recordings:
                    return recordings[0]
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur lors de la recherche MusicBrainz: {e}")
            return None
    
    def _get_recording_details(self, recording_id: str) -> Optional[Dict]:
        """Récupérer les détails complets d'un enregistrement"""
        try:
            url = f"{self.musicbrainz_base_url}/recording/{recording_id}"
            params = {
                "inc": "releases+artists+genres",
                "fmt": "json"
            }
            
            headers = {
                "User-Agent": "MusicHome/1.0 (https://github.com/your-repo)",
                "Accept": "application/json"
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json()
            
            return None
            
        except Exception as e:
            logger.debug(f"Erreur lors de la récupération des détails: {e}")
            return None
    
    def _extract_artist_from_recording(self, recording: Dict) -> Optional[str]:
        """Extraire le nom de l'artiste principal"""
        try:
            artist_credits = recording.get("artist-credit", [])
            if artist_credits:
                # Prendre le premier artiste
                artist = artist_credits[0].get("artist", {})
                return artist.get("name")
        except Exception:
            pass
        return None
    
    def _extract_album_from_recording(self, recording: Dict) -> Optional[str]:
        """Extraire le nom de l'album"""
        try:
            releases = recording.get("releases", [])
            if releases:
                # Prendre la première release (généralement la plus récente)
                release = releases[0]
                return release.get("title")
        except Exception:
            pass
        return None
    
    def _extract_year_from_recording(self, recording: Dict) -> Optional[int]:
        """Extraire l'année de sortie"""
        try:
            releases = recording.get("releases", [])
            if releases:
                release = releases[0]
                date = release.get("date")
                if date:
                    # Extraire l'année (format peut être "2023" ou "2023-01-01")
                    year_match = re.search(r'(\d{4})', date)
                    if year_match:
                        return int(year_match.group(1))
        except Exception:
            pass
        return None
    
    def _extract_genre_from_recording(self, recording: Dict) -> Optional[str]:
        """Extraire le genre"""
        try:
            tags = recording.get("tags", [])
            if tags:
                # Prendre le tag le plus populaire
                sorted_tags = sorted(tags, key=lambda x: x.get("count", 0), reverse=True)
                if sorted_tags:
                    return sorted_tags[0].get("name")
        except Exception:
            pass
        return None
    
    def _get_cover_art_url(self, recording: Dict) -> Optional[str]:
        """Récupérer l'URL de la pochette d'album"""
        try:
            releases = recording.get("releases", [])
            if releases:
                release = releases[0]
                release_id = release.get("id")
                
                if release_id:
                    # Récupérer la pochette depuis Cover Art Archive
                    cover_url = f"{self.cover_art_base_url}/release/{release_id}/front"
                    
                    # Vérifier que l'image existe
                    response = requests.head(cover_url, timeout=5, allow_redirects=True)
                    if response.status_code == 200:
                        return cover_url
        except Exception:
            pass
        return None
    
    def _download_cover_art(self, file_path: Path, cover_url: str) -> bool:
        """Télécharger et intégrer la pochette dans le fichier audio"""
        try:
            # Télécharger l'image
            response = requests.get(cover_url, timeout=10)
            if response.status_code != 200:
                return False
            
            image_data = response.content
            
            # Intégrer dans le fichier FLAC
            if file_path.suffix.lower() == '.flac':
                audio = FLAC(str(file_path))
                
                picture = Picture()
                picture.type = 3  # Cover (front)
                picture.mime = "image/jpeg"  # Cover Art Archive fournit généralement du JPEG
                picture.data = image_data
                
                audio.add_picture(picture)
                audio.save()
                
                logger.info(f"✅ Pochette intégrée: {file_path.name}")
                return True
            
        except Exception as e:
            logger.warning(f"Impossible de télécharger la pochette: {e}")
        
        return False
    
    def _clean_filename_title(self, title: str) -> str:
        """Nettoyer le titre en enlevant les informations inutiles"""
        if not title:
            return ""
        
        cleaned = title
        
        # Appliquer tous les patterns de nettoyage
        for pattern in self.cleanup_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)
        
        # Nettoyer les espaces multiples
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Enlever les caractères spéciaux en fin de titre
        cleaned = cleaned.rstrip(' -')
        
        return cleaned
    
    def _clean_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Nettoyer toutes les métadonnées"""
        cleaned = {}
        
        for key, value in metadata.items():
            if isinstance(value, str):
                # Enlever les URLs
                value = re.sub(r'https?://[^\s]+', '', value)
                value = re.sub(r'www\.[^\s]+', '', value)
                # Nettoyer les espaces
                value = re.sub(r'\s+', ' ', value).strip()
                # Limiter la longueur
                if len(value) > 200:
                    value = value[:200]
            cleaned[key] = value
        
        return cleaned
    
    def _merge_metadata(
        self,
        current: Dict[str, Any],
        enriched: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fusionner les métadonnées actuelles avec les enrichies"""
        merged = current.copy()
        
        if enriched:
            # Priorité aux métadonnées enrichies
            for key in ["artist", "album", "title", "year", "genre"]:
                if enriched.get(key):
                    merged[key] = enriched[key]
                elif not merged.get(key):
                    # Garder la valeur actuelle si pas d'enrichissement
                    pass
        
        return merged
    
    def _reorganize_file(
        self,
        file_path: Path,
        metadata: Dict[str, Any]
    ) -> Path:
        """Réorganiser le fichier avec les nouvelles métadonnées"""
        try:
            # Utiliser le service d'organisation existant
            new_path = self.organizer_service.organize_file(
                file_path,
                metadata=metadata
            )
            
            if new_path != file_path:
                logger.info(f"📦 Fichier réorganisé: {file_path.name} -> {new_path.name}")
            
            return new_path
            
        except Exception as e:
            logger.warning(f"Impossible de réorganiser {file_path}: {e}")
            return file_path

