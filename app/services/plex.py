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
        
        url = f"{self.server_url}/library/sections/{self.library_id}/refresh"
        headers = {"X-Plex-Token": self.token}
        
        try:
            response = requests.post(url, headers=headers, timeout=10)
            if response.status_code == 200:
                logger.info("Scan Plex déclenché avec succès")
                return True
            else:
                logger.warning(f"Échec du scan Plex: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Erreur lors du scan Plex: {str(e)}")
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

