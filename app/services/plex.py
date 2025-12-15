"""Service d'intégration avec Plex API"""
import requests
from typing import Optional
from app.config import settings
import logging

logger = logging.getLogger(__name__)


class PlexService:
    """Service pour interagir avec l'API Plex"""
    
    def __init__(self):
        self.server_url = settings.PLEX_SERVER_URL
        self.token = settings.PLEX_TOKEN
        self.library_id = settings.PLEX_LIBRARY_SECTION_ID
        self.enabled = settings.PLEX_AUTO_SCAN
    
    def is_configured(self) -> bool:
        """Vérifier si Plex est configuré"""
        return all([
            self.server_url,
            self.token,
            self.library_id is not None
        ])
    
    def scan_library(self) -> bool:
        """
        Déclencher un scan de la bibliothèque musicale
        
        Returns:
            True si le scan a été déclenché avec succès
        """
        if not self.enabled or not self.is_configured():
            logger.debug("Plex scan désactivé ou non configuré")
            return False
        
        # Essayer d'abord avec le library_id configuré
        library_id = self.library_id
        url = f"{self.server_url}/library/sections/{library_id}/refresh"
        headers = {"X-Plex-Token": self.token}
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info("Scan Plex déclenché avec succès")
                return True
            elif response.status_code == 404:
                # Si 404, essayer de trouver automatiquement la section musique
                logger.warning(f"Library ID {library_id} non trouvé, recherche automatique...")
                return self._scan_library_auto()
            else:
                logger.warning(f"Échec du scan Plex: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Erreur lors du scan Plex: {str(e)}")
            return False
    
    def _scan_library_auto(self) -> bool:
        """Trouver automatiquement la section musique et scanner"""
        try:
            # Lister toutes les sections
            url = f"{self.server_url}/library/sections"
            headers = {"X-Plex-Token": self.token}
            response = requests.get(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)
                
                # Chercher la section de type "artist" (musique)
                for section in root.findall('Directory'):
                    section_type = section.get('type')
                    if section_type == 'artist':
                        section_id = section.get('key')
                        section_title = section.get('title')
                        
                        # Scanner cette section
                        scan_url = f"{self.server_url}/library/sections/{section_id}/refresh"
                        scan_response = requests.post(scan_url, headers=headers, timeout=10)
                        
                        if scan_response.status_code == 200:
                            logger.info(f"✅ Scan Plex réussi avec section '{section_title}' (ID: {section_id})")
                            # Mettre à jour le library_id pour la prochaine fois
                            self.library_id = int(section_id)
                            return True
                        else:
                            logger.warning(f"Échec du scan avec section ID {section_id}: {scan_response.status_code}")
            
            logger.error("Aucune section musique trouvée")
            return False
            
        except Exception as e:
            logger.error(f"Erreur lors de la recherche automatique: {str(e)}")
            return False
    
    def get_library_info(self) -> Optional[dict]:
        """Obtenir les informations de la bibliothèque"""
        if not self.is_configured():
            return None
        
        url = f"{self.server_url}/library/sections/{self.library_id}"
        headers = {"X-Plex-Token": self.token}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            logger.error(f"Erreur lors de la récupération des infos: {str(e)}")
        
        return None
    
    def force_refresh_metadata(self) -> bool:
        """
        Forcer un rafraîchissement complet des métadonnées Plex
        
        Cette méthode effectue un scan complet de la bibliothèque
        et force Plex à relire toutes les métadonnées des fichiers.
        
        Returns:
            True si le refresh a été déclenché avec succès
        """
        if not self.is_configured():
            logger.debug("Plex non configuré")
            return False
        
        try:
            headers = {"X-Plex-Token": self.token}
            
            # 1. Scanner la bibliothèque (avec auto-détection si nécessaire)
            if not self.scan_library():
                return False
            
            logger.info("✅ Scan de la bibliothèque Plex lancé")
            
            # 2. Forcer l'analyse des métadonnées (force=1)
            analyze_url = f"{self.server_url}/library/sections/{self.library_id}/analyze"
            response = requests.post(analyze_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                logger.info("✅ Analyse des métadonnées Plex forcée")
            else:
                logger.warning(f"L'analyse a échoué: {response.status_code}")
            
            return True
            
        except Exception as e:
            logger.error(f"Erreur lors du refresh Plex: {str(e)}")
            return False
    
    def empty_trash(self) -> bool:
        """
        Vider la corbeille de la bibliothèque Plex
        
        Returns:
            True si la corbeille a été vidée avec succès
        """
        if not self.is_configured():
            logger.debug("Plex non configuré")
            return False
        
        try:
            url = f"{self.server_url}/library/sections/{self.library_id}/emptyTrash"
            headers = {"X-Plex-Token": self.token}
            
            response = requests.put(url, headers=headers, timeout=30)
            if response.status_code == 200:
                logger.info("✅ Corbeille Plex vidée")
                return True
            else:
                logger.warning(f"Échec du vidage de la corbeille: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"Erreur lors du vidage de la corbeille: {str(e)}")
            return False

