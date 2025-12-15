"""Script de nettoyage et fusion des artistes en double"""
import logging
import shutil
from pathlib import Path
from collections import defaultdict
from typing import Dict, List
from app.config import settings
from app.services.metadata import MetadataService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ArtistCleanupService:
    """Service pour nettoyer et fusionner les artistes en double"""
    
    def __init__(self):
        self.music_dir = settings.MUSIC_DIR
        self.metadata_service = MetadataService()
        
        # Règles de fusion des artistes
        self.artist_mappings = {
            "Sofiane Officiel": "Sofiane",
            "sofiane officiel": "Sofiane",
            "SOFIANE OFFICIEL": "Sofiane",
            "B20baOfficiel": "Booba",
            "Niska Officiel": "Niska",
            "DORETDEPLATINE": "JuL",
            "ElGrandeToto": "El Grande Toto",
            "OrbanOnTheBeat": "Orban",
            "FAST BOY": "Fast Boy",
            "Unknown Artist": None,  # Nécessite analyse manuelle
        }
    
    def clean_all_artists(self, dry_run: bool = False) -> Dict:
        """
        Nettoyer et fusionner tous les artistes
        
        Args:
            dry_run: Si True, simule sans modification
        """
        logger.info("🎨 Démarrage du nettoyage des artistes...")
        
        stats = {
            "artists_found": 0,
            "artists_merged": 0,
            "files_moved": 0,
            "unknown_fixed": 0,
            "errors": 0
        }
        
        # Analyser les artistes existants
        artist_dirs = [d for d in self.music_dir.iterdir() if d.is_dir()]
        stats["artists_found"] = len(artist_dirs)
        
        logger.info(f"📁 {stats['artists_found']} artistes trouvés")
        
        # Traiter Unknown Artist en premier
        unknown_artist_dir = self.music_dir / "Unknown Artist"
        if unknown_artist_dir.exists():
            logger.info("\n🔍 Traitement de 'Unknown Artist'...")
            fixed = self._fix_unknown_artist(unknown_artist_dir, dry_run)
            stats["unknown_fixed"] = fixed
        
        # Fusionner les artistes en double
        for original_name, target_name in self.artist_mappings.items():
            if target_name is None:
                continue
                
            original_dir = self.music_dir / original_name
            if not original_dir.exists():
                continue
            
            target_dir = self.music_dir / target_name
            
            logger.info(f"\n🔀 Fusion: '{original_name}' → '{target_name}'")
            
            try:
                if not dry_run:
                    moved = self._merge_artist_dirs(original_dir, target_dir)
                    stats["files_moved"] += moved
                    stats["artists_merged"] += 1
                else:
                    logger.info(f"   [DRY RUN] Fusionnerait {original_name} vers {target_name}")
                    stats["artists_merged"] += 1
            except Exception as e:
                logger.error(f"❌ Erreur lors de la fusion de {original_name}: {e}")
                stats["errors"] += 1
        
        logger.info(f"\n✅ Nettoyage terminé:")
        logger.info(f"   - Artistes fusionnés: {stats['artists_merged']}")
        logger.info(f"   - Fichiers déplacés: {stats['files_moved']}")
        logger.info(f"   - Unknown Artist corrigés: {stats['unknown_fixed']}")
        logger.info(f"   - Erreurs: {stats['errors']}")
        
        return stats
    
    def _fix_unknown_artist(self, unknown_dir: Path, dry_run: bool = False) -> int:
        """Corriger les fichiers dans Unknown Artist"""
        fixed_count = 0
        
        for audio_file in unknown_dir.rglob("*.flac"):
            try:
                # Essayer d'extraire l'artiste du nom du fichier
                filename = audio_file.stem
                logger.info(f"   📄 Analyse: {filename}")
                
                # Pattern: "Artist - Title"
                if " - " in filename:
                    parts = filename.split(" - ", 1)
                    potential_artist = parts[0].strip()
                    title = parts[1].strip() if len(parts) > 1 else filename
                    
                    # Nettoyer l'artiste
                    artist = self._clean_artist_name(potential_artist)
                    
                    if artist and artist.lower() != "unknown":
                        logger.info(f"   ✅ Artiste détecté: {artist}")
                        
                        if not dry_run:
                            # Mettre à jour les métadonnées
                            metadata = self.metadata_service.extract_metadata(audio_file)
                            metadata["artist"] = artist
                            metadata["title"] = title
                            
                            # Créer le dossier de l'artiste
                            artist_dir = self.music_dir / artist
                            album_name = metadata.get("album") or "Unknown Album"
                            year = metadata.get("year")
                            if year:
                                album_dir_name = f"{album_name} ({year})"
                            else:
                                album_dir_name = album_name
                            
                            dest_dir = artist_dir / album_dir_name
                            dest_dir.mkdir(parents=True, exist_ok=True)
                            
                            # Déplacer le fichier
                            dest_file = dest_dir / audio_file.name
                            shutil.move(str(audio_file), str(dest_file))
                            
                            # Mettre à jour les métadonnées
                            self.metadata_service.update_metadata(
                                dest_file,
                                artist=artist,
                                title=title
                            )
                            
                            logger.info(f"   📦 Déplacé vers: {artist}/{album_dir_name}/")
                            fixed_count += 1
                        else:
                            logger.info(f"   [DRY RUN] Déplacerait vers: {artist}")
                            fixed_count += 1
                
            except Exception as e:
                logger.error(f"   ❌ Erreur: {e}")
        
        # Supprimer le dossier Unknown Artist s'il est vide
        if not dry_run and unknown_dir.exists():
            try:
                # Vérifier s'il reste des fichiers
                remaining_files = list(unknown_dir.rglob("*.flac"))
                if not remaining_files:
                    shutil.rmtree(unknown_dir)
                    logger.info(f"   🗑️ Dossier 'Unknown Artist' supprimé (vide)")
            except Exception as e:
                logger.warning(f"   ⚠️ Impossible de supprimer le dossier: {e}")
        
        return fixed_count
    
    def _merge_artist_dirs(self, source_dir: Path, target_dir: Path) -> int:
        """Fusionner deux dossiers d'artistes"""
        files_moved = 0
        
        # Créer le dossier cible si nécessaire
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # Parcourir tous les albums dans le dossier source
        for album_dir in source_dir.iterdir():
            if not album_dir.is_dir():
                continue
            
            target_album_dir = target_dir / album_dir.name
            
            # Si l'album existe déjà dans la cible, fusionner
            if target_album_dir.exists():
                logger.info(f"   📂 Fusion de l'album: {album_dir.name}")
                for audio_file in album_dir.rglob("*.flac"):
                    dest_file = target_album_dir / audio_file.name
                    if not dest_file.exists():
                        shutil.move(str(audio_file), str(dest_file))
                        files_moved += 1
                        logger.info(f"      ✅ {audio_file.name}")
            else:
                # Déplacer tout l'album
                logger.info(f"   📂 Déplacement de l'album: {album_dir.name}")
                shutil.move(str(album_dir), str(target_album_dir))
                album_files = len(list(target_album_dir.rglob("*.flac")))
                files_moved += album_files
                logger.info(f"      ✅ {album_files} fichiers déplacés")
        
        # Supprimer le dossier source s'il est vide
        try:
            if source_dir.exists() and not any(source_dir.iterdir()):
                source_dir.rmdir()
                logger.info(f"   🗑️ Dossier source supprimé: {source_dir.name}")
        except Exception as e:
            logger.warning(f"   ⚠️ Impossible de supprimer {source_dir}: {e}")
        
        return files_moved
    
    def _clean_artist_name(self, name: str) -> str:
        """Nettoyer le nom d'un artiste"""
        if not name:
            return ""
        
        # Appliquer les mappings
        for pattern, replacement in self.artist_mappings.items():
            if replacement and pattern.lower() in name.lower():
                return replacement
        
        # Supprimer "Officiel" du nom
        name = name.replace(" Officiel", "").replace(" officiel", "")
        name = name.replace("Officiel", "").replace("officiel", "")
        
        # Nettoyer les espaces
        name = " ".join(name.split())
        
        return name.strip()


def main():
    """Point d'entrée du script"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Nettoyer et fusionner les artistes en double")
    parser.add_argument("--dry-run", action="store_true", help="Mode simulation (pas de modification)")
    parser.add_argument("--verbose", action="store_true", help="Mode verbeux")
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    service = ArtistCleanupService()
    stats = service.clean_all_artists(dry_run=args.dry_run)
    
    print("\n" + "="*60)
    print("RÉSUMÉ")
    print("="*60)
    print(f"Artistes fusionnés: {stats['artists_merged']}")
    print(f"Fichiers déplacés: {stats['files_moved']}")
    print(f"Unknown Artist corrigés: {stats['unknown_fixed']}")
    print(f"Erreurs: {stats['errors']}")
    print("="*60)


if __name__ == "__main__":
    main()

