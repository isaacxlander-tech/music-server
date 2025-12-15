"""Queue Manager - Handle download queue with database persistence"""
import asyncio
import logging
import fcntl
import os
from pathlib import Path
from typing import Optional, List
from sqlalchemy import and_, text
from sqlalchemy.orm import Session

from app.models.queue import QueueItem, QueueStatus
from app.models.track import Track, SourceType
from app.database.db import SessionLocal
from app.services.task_manager import TaskManager
from app.config import settings

logger = logging.getLogger(__name__)


class QueueManager:
    """Manage download queue with database persistence"""
    
    def __init__(self, task_manager: TaskManager):
        self.task_manager = task_manager
        self.is_processing = False
        self.current_task_id: Optional[str] = None
        self._lock = asyncio.Lock()
        self._db_lock = asyncio.Lock()  # Lock pour les opérations DB atomiques (intra-processus)
        # Lock fichier système pour synchronisation inter-processus
        lock_file_path = settings.BASE_DIR / "database" / "queue.lock"
        lock_file_path.parent.mkdir(parents=True, exist_ok=True)
        self._file_lock_path = lock_file_path
        logger.info("Queue manager initialized with database persistence")
    
    def _get_db(self) -> Session:
        """Get database session"""
        return SessionLocal()
    
    def add_to_queue(self, url: str, source: Optional[SourceType] = None, title: Optional[str] = None) -> dict:
        """Add URL to queue with optional title"""
        db = self._get_db()
        try:
            # Check if URL is already in queue (PENDING or PROCESSING)
            existing = db.query(QueueItem).filter(
                and_(
                    QueueItem.url == url,
                    QueueItem.status.in_([QueueStatus.PENDING, QueueStatus.PROCESSING])
                )
            ).first()
            
            if existing:
                logger.info(f"URL already in queue (status: {existing.status}): {url}")
                return existing.to_dict()
            
            # Check if track already exists in database (already downloaded)
            existing_track = db.query(Track).filter(Track.source_url == url).first()
            if existing_track:
                logger.info(f"Track already exists in database (ID: {existing_track.id}), skipping: {url}")
                # Return a dict representing a completed item
                return {
                    'id': None,
                    'url': url,
                    'source': source,
                    'title': title or existing_track.title,
                    'status': QueueStatus.COMPLETED,
                    'created_at': None,
                    'task_id': None
                }
            
            # Create new queue item
            queue_item = QueueItem(
                url=url,
                source=source,
                title=title,
                status=QueueStatus.PENDING
            )
            db.add(queue_item)
            db.commit()
            db.refresh(queue_item)
            
            logger.info(f"Added to queue: {url} (title: {title})")
            return queue_item.to_dict()
        finally:
            db.close()
    
    def add_multiple_to_queue(self, urls: List[str], source: Optional[SourceType] = None, titles: Optional[List[str]] = None) -> List[dict]:
        """Add multiple URLs to queue with optional titles"""
        results = []
        for i, url in enumerate(urls):
            title = titles[i] if titles and i < len(titles) else None
            result = self.add_to_queue(url, source, title)
            results.append(result)
        return results
    
    def get_queue(self) -> List[dict]:
        """Get current queue status with titles from Track table for completed items"""
        db = self._get_db()
        try:
            items = db.query(QueueItem).order_by(QueueItem.created_at.asc()).all()
            result = []
            for item in items:
                item_dict = item.to_dict()
                # If title is missing and item is completed, try to get it from Track table
                if not item_dict.get('title') and item.status == QueueStatus.COMPLETED:
                    track = db.query(Track).filter(Track.source_url == item.url).first()
                    if track:
                        item_dict['title'] = track.title
                        # Update the queue item with the title for future queries
                        if not item.title:
                            item.title = track.title
                            db.commit()
                result.append(item_dict)
            return result
        finally:
            db.close()
    
    def remove_from_queue(self, url: str) -> bool:
        """Remove URL from queue (if not processing)"""
        db = self._get_db()
        try:
            item = db.query(QueueItem).filter(
                and_(QueueItem.url == url, QueueItem.status == QueueStatus.PENDING)
            ).first()
            
            if item:
                db.delete(item)
                db.commit()
                logger.info(f"Removed from queue: {url}")
                return True
            return False
        finally:
            db.close()
    
    def clear_queue(self):
        """Clear ALL items from queue (including completed/failed)"""
        db = self._get_db()
        try:
            # Get ALL items
            items_to_remove = db.query(QueueItem).all()
            
            task_ids_to_clean = [item.task_id for item in items_to_remove if item.task_id]
            
            # Delete ALL items
            for item in items_to_remove:
                db.delete(item)
            
            db.commit()
            
            # Clean up tasks in TaskManager
            for task_id in task_ids_to_clean:
                if task_id:
                    self.task_manager.delete_task(task_id)
            
            # Reset current task ID
            self.current_task_id = None
            
            logger.info(f"Queue cleared completely (removed {len(items_to_remove)} items)")
        finally:
            db.close()
    
    def get_queue_size(self) -> int:
        """Get queue size (only pending items)"""
        db = self._get_db()
        try:
            return db.query(QueueItem).filter(QueueItem.status == QueueStatus.PENDING).count()
        finally:
            db.close()
    
    def get_status(self) -> dict:
        """Get queue processor status"""
        db = self._get_db()
        try:
            pending_count = db.query(QueueItem).filter(QueueItem.status == QueueStatus.PENDING).count()
            processing_count = db.query(QueueItem).filter(QueueItem.status == QueueStatus.PROCESSING).count()
            completed_count = db.query(QueueItem).filter(QueueItem.status == QueueStatus.COMPLETED).count()
            failed_count = db.query(QueueItem).filter(QueueItem.status == QueueStatus.FAILED).count()
            
            return {
                "is_processing": self.is_processing,
                "pending": pending_count,
                "processing": processing_count,
                "completed": completed_count,
                "failed": failed_count,
                "total": pending_count + processing_count + completed_count + failed_count
            }
        finally:
            db.close()
    
    def _get_next_item_with_file_lock(self) -> Optional[dict]:
        """Get next pending item with file lock (synchronous, called from thread)
        The file lock is held for the entire duration to prevent race conditions"""
        lock_file = None
        try:
            # Ouvrir le fichier de lock en mode append pour éviter les erreurs si le fichier n'existe pas
            lock_file = open(self._file_lock_path, 'a+')
            # Acquérir un verrou exclusif (bloquant) - bloque jusqu'à ce qu'il soit disponible
            # Ce verrou est maintenu pendant toute la durée de la récupération et du marquage
            logger.debug(f"🔒 Attempting to acquire file lock: {self._file_lock_path}")
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            logger.debug(f"🔒 File lock acquired successfully")
            
            try:
                db = self._get_db()
                try:
                    # BEGIN IMMEDIATE obtient un verrou exclusif sur SQLite
                    # Combiné avec le file lock, cela garantit l'atomicité entre processus
                    db.execute(text("BEGIN IMMEDIATE"))
                    
                    # Find the oldest PENDING item
                    item = db.query(QueueItem).filter(
                        QueueItem.status == QueueStatus.PENDING
                    ).order_by(QueueItem.created_at.asc()).with_for_update().first()
                    
                    if not item:
                        db.rollback()
                        return None
                    
                    # Récupérer les valeurs AVANT de modifier
                    item_data = {
                        'id': item.id,
                        'url': item.url,
                        'source': item.source,
                        'title': item.title,
                        'status': QueueStatus.PROCESSING,
                        'created_at': item.created_at,
                        'task_id': item.task_id
                    }
                    
                    # Mark as PROCESSING atomically in the same transaction
                    item.status = QueueStatus.PROCESSING
                    db.commit()
                    
                    logger.info(f"🔒 Atomically retrieved and marked item {item.id} as PROCESSING (URL: {item.url[:50]}...)")
                    # Le lock est maintenu jusqu'à la fin de cette fonction
                    # Il sera libéré dans le finally
                    return item_data
                except Exception as e:
                    db.rollback()
                    logger.error(f"Error getting next item: {e}", exc_info=True)
                    return None
                finally:
                    db.close()
            finally:
                # Libérer le verrou fichier APRÈS avoir terminé la transaction DB
                # Cela garantit qu'un seul processus peut récupérer un item à la fois
                if lock_file:
                    try:
                        logger.debug(f"🔓 Releasing file lock")
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                        lock_file.close()
                        logger.debug(f"🔓 File lock released")
                    except Exception as e:
                        logger.error(f"Error releasing file lock: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Error acquiring file lock: {e}", exc_info=True)
            if lock_file:
                try:
                    lock_file.close()
                except Exception:
                    pass
            return None
    
    async def get_next_item_async(self) -> Optional[dict]:
        """Get next pending item from queue and mark it as PROCESSING atomically
        Uses file lock (inter-processus) + async lock (intra-processus) + BEGIN IMMEDIATE
        Returns a dict with item data to avoid DetachedInstanceError"""
        # Verrou async pour éviter les race conditions au sein du même processus
        async with self._db_lock:
            # Exécuter le file lock dans un thread pour ne pas bloquer l'event loop
            # Le file lock garantit qu'un seul processus (worker) peut récupérer un item
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._get_next_item_with_file_lock)
    
    def get_item_by_url(self, url: str) -> Optional[QueueItem]:
        """Get queue item by URL"""
        db = self._get_db()
        try:
            item = db.query(QueueItem).filter(QueueItem.url == url).first()
            if item:
                db.expunge(item)
            return item
        finally:
            db.close()
    
    def get_item_by_task_id(self, task_id: str) -> Optional[QueueItem]:
        """Get queue item by task ID"""
        db = self._get_db()
        try:
            item = db.query(QueueItem).filter(QueueItem.task_id == task_id).first()
            if item:
                db.expunge(item)
            return item
        finally:
            db.close()
    
    def update_item_status(self, item_id: int, status: QueueStatus, progress: int = None, 
                          message: str = None, error: str = None, title: str = None):
        """Update queue item status"""
        db = self._get_db()
        try:
            item = db.query(QueueItem).filter(QueueItem.id == item_id).first()
            if item:
                item.status = status
                if progress is not None:
                    item.progress = progress
                if message is not None:
                    item.message = message
                if error is not None:
                    item.error = error
                if title is not None:
                    item.title = title
                db.commit()
                logger.debug(f"Updated item {item_id}: status={status}, progress={progress}, message={message}")
        finally:
            db.close()
    
    async def start_processing(self, process_download_func):
        """Start processing queue (should be called once)"""
        if self.is_processing:
            logger.warning("Queue processor already running")
            return
        
        self.is_processing = True
        logger.info("Queue processor started")
        
        # Sémaphore comme attribut d'instance pour qu'il persiste
        # Permettre 50 téléchargements simultanés maintenant que la conversion est corrigée
        if not hasattr(self, '_semaphore'):
            self._semaphore = asyncio.Semaphore(50)
        
        while self.is_processing:
            try:
                # Attendre qu'un slot soit disponible (max 50 téléchargements simultanés)
                async with self._semaphore:
                    # Récupérer l'item (utilise get_next_item_async qui a son propre lock DB)
                    item = await self.get_next_item_async()  # Déjà marqué comme PROCESSING atomiquement
                    
                    if not item:
                        # Pas d'item, attendre un peu mais RESTER dans le sémaphore
                        await asyncio.sleep(2)
                        # Ne pas utiliser continue, juste continuer la boucle
                    else:
                        # Item déjà marqué comme PROCESSING par get_next_item() (atomiquement)
                        # item est maintenant un dict, pas un objet QueueItem
                        item_id = item['id']
                        item_url = item['url']
                        self.current_task_id = None
                        
                        # Process the item (toujours dans le sémaphore)
                        logger.info(f"Processing queue item: {item_url}")
                        
                        # Créer le task IMMÉDIATEMENT pour avoir un task_id
                        task_id = self.task_manager.create_task(item_url)
                        
                        # Mettre à jour l'item avec task_id et progression initiale
                        db = self._get_db()
                        try:
                            db_item = db.query(QueueItem).filter(QueueItem.id == item_id).first()
                            if db_item:
                                db_item.task_id = task_id
                                db_item.progress = 0
                                db.commit()
                        finally:
                            db.close()
                        
                        # Update status message avec progression initiale
                        self.update_item_status(item_id, QueueStatus.PROCESSING, progress=0, message="En attente...")
                        
                        try:
                            # Process download in thread pool (sync function)
                            # Le sémaphore garantit un maximum de 50 téléchargements simultanés
                            import concurrent.futures
                            loop = asyncio.get_event_loop()
                            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
                                await loop.run_in_executor(pool, process_download_func, item_url, task_id, item_id)
                            
                        except Exception as e:
                            logger.error(f"Error processing queue item: {e}", exc_info=True)
                            self.update_item_status(item_id, QueueStatus.FAILED, progress=0, 
                                                  message="Erreur", error=str(e))
                        
                        # Small delay between items (toujours dans le sémaphore)
                        await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in queue processor: {e}", exc_info=True)
                await asyncio.sleep(5)
    
    def stop_processing(self):
        """Stop processing queue"""
        self.is_processing = False
        logger.info("Queue processor stopped")


# Singleton instance
_queue_manager = None


def get_queue_manager(task_manager: TaskManager) -> QueueManager:
    """Get or create queue manager instance"""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = QueueManager(task_manager)
    return _queue_manager
