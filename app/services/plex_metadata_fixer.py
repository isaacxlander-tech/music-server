"""Script de correction des métadonnées pour Plex"""
import logging
from pathlib import Path
from typing import Dict, Any
from app.config import settings
from app.services.metadata import MetadataService
from app.services.organizer import OrganizerService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PlexMetadataFixer:
    """Service pour corriger les métadonnées pour Plex"""
    
    def __init__(self):
        self.music_dir = settings.MUSIC_DIR
        self.metadata_service = MetadataService()
        self.organizer_service = OrganizerService()
    
    def fix_all_metadata(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        Corriger toutes les métadonnées en se basant sur la structure des dossiers
        
        Args:
            dry_run: Si True, simule sans modification
        """
        logger.info("🔧 Démarrage de la correction des métadonnées...")
        
        stats = {
            "total_files": 0,
            "fixed": 0,
            "errors": 0
        }
        
        # Parcourir tous les fichiers audio
        for audio_file in self.music_dir.rglob("*.flac"):
            stats["total_files"] += 1
            
            try:
                # Extraire les informations depuis le chemin
                # Format: music/Artist/Album (Year)/Title.flac
                parts = audio_file.relative_to(self.music_dir).parts
                
                if len(parts) < 3:
                    logger.warning(f"⚠️ Structure invalide: {audio_file}")
                    continue
                
                artist_from_path = parts[0]
                album_from_path = parts[1]
                
                # Extraire l'année de l'album si présente
                year = None
                import re
                year_match = re.search(r'\((\d{4})\)', album_from_path)
                if year_match:
                    year = int(year_match.group(1))
                    album_clean = re.sub(r'\s*\(\d{4}\)\s*', '', album_from_path).strip()
                else:
                    album_clean = album_from_path
                
                # Extraire le titre du fichier (sans extension)
                title_from_file = audio_file.stem
                
                # Lire les métadonnées actuelles
                current_metadata = self.metadata_service.extract_metadata(audio_file)
                
                # Vérifier si les métadonnées correspondent
                needs_fix = False
                if current_metadata.get("artist") != artist_from_path:
                    needs_fix = True
                if current_metadata.get("album") != album_clean:
                    needs_fix = True
                if current_metadata.get("title") != title_from_file:
                    needs_fix = True
                
                if needs_fix:
                    logger.info(f"\n📝 Correction: {audio_file.name}")
                    logger.info(f"   Artiste: '{current_metadata.get('artist')}' → '{artist_from_path}'")
                    logger.info(f"   Album: '{current_metadata.get('album')}' → '{album_clean}'")
                    logger.info(f"   Titre: '{current_metadata.get('title')}' → '{title_from_file}'")
                    
                    if not dry_run:
                        # Mettre à jour les métadonnées
                        self.metadata_service.update_metadata(
                            audio_file,
                            artist=artist_from_path,
                            album=album_clean,
                            title=title_from_file,
                            year=year or current_metadata.get("year"),
                            genre=current_metadata.get("genre")
                        )
                        logger.info(f"   ✅ Métadonnées mises à jour")
                    else:
                        logger.info(f"   [DRY RUN] Métadonnées à mettre à jour")
                    
                    stats["fixed"] += 1
                
            except Exception as e:
                logger.error(f"❌ Erreur: {audio_file}: {e}")
                stats["errors"] += 1
        
        logger.info(f"\n✅ Correction terminée:")
        logger.info(f"   - Fichiers traités: {stats['total_files']}")
        logger.info(f"   - Fichiers corrigés: {stats['fixed']}")
        logger.info(f"   - Erreurs: {stats['errors']}")
        
        return stats


def main():
    """Point d'entrée du script"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Corriger les métadonnées pour Plex")
    parser.add_argument("--dry-run", action="store_true", help="Mode simulation")
    
    args = parser.parse_args()
    
    fixer = PlexMetadataFixer()
    stats = fixer.fix_all_metadata(dry_run=args.dry_run)
    
    print("\n" + "="*60)
    print("RÉSUMÉ")
    print("="*60)
    print(f"Fichiers traités: {stats['total_files']}")
    print(f"Fichiers corrigés: {stats['fixed']}")
    print(f"Erreurs: {stats['errors']}")
    print("="*60)


if __name__ == "__main__":
    main()

