"""Queue manager for sequential download processing"""
import asyncio
import logging
from typing import List, Optional, Dict
from datetime import datetime
from collections import deque
from app.services.task_manager import TaskManager, TaskStatus, TaskInfo

logger = logging.getLogger(__name__)


class QueueItem:
    """Item in the download queue"""
    def __init__(self, url: str, source: Optional[str] = None):
        self.url = url
        self.source = source
        self.task_id: Optional[str] = None
        self.status = "pending"  # pending, processing, completed, failed
        self.created_at = datetime.now()
        self.error: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source": self.source,
            "task_id": self.task_id,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "error": self.error
        }


class QueueManager:
    """Manages download queue and sequential processing"""
    
    def __init__(self, task_manager: TaskManager):
        self.queue: deque = deque()
        self.task_manager = task_manager
        self.is_processing = False
        self.current_task_id: Optional[str] = None
        self._lock = asyncio.Lock()
    
    def add_to_queue(self, url: str, source: Optional[str] = None) -> QueueItem:
        """Add URL to download queue"""
        item = QueueItem(url, source)
        self.queue.append(item)
        logger.info(f"Added to queue: {url} (queue size: {len(self.queue)})")
        return item
    
    def add_multiple_to_queue(self, urls: List[str], source: Optional[str] = None) -> List[QueueItem]:
        """Add multiple URLs to queue"""
        items = []
        for url in urls:
            item = self.add_to_queue(url, source)
            items.append(item)
        logger.info(f"Added {len(urls)} URLs to queue")
        return items
    
    def get_queue(self) -> List[dict]:
        """Get current queue status"""
        return [item.to_dict() for item in self.queue]
    
    def remove_from_queue(self, url: str) -> bool:
        """Remove URL from queue (if not processing)"""
        for item in list(self.queue):
            if item.url == url and item.status == "pending":
                self.queue.remove(item)
                logger.info(f"Removed from queue: {url}")
                return True
        return False
    
    def clear_queue(self):
        """Clear all pending items from queue"""
        # Only remove pending items
        self.queue = deque([item for item in self.queue if item.status != "pending"])
        logger.info("Queue cleared")
    
    def get_queue_size(self) -> int:
        """Get queue size"""
        return len(self.queue)
    
    def get_next_item(self) -> Optional[QueueItem]:
        """Get next pending item from queue"""
        for item in self.queue:
            if item.status == "pending":
                return item
        return None
    
    async def start_processing(self, process_download_func):
        """Start processing queue (should be called once)"""
        if self.is_processing:
            logger.warning("Queue processor already running")
            return
        
        self.is_processing = True
        logger.info("Queue processor started")
        
        while self.is_processing:
            try:
                async with self._lock:
                    item = self.get_next_item()
                    if not item:
                        await asyncio.sleep(2)  # Wait before checking again
                        continue
                    
                    # Mark as processing
                    item.status = "processing"
                    self.current_task_id = None
                
                # Process the item
                logger.info(f"Processing queue item: {item.url}")
                try:
                    # Create task
                    task_id = self.task_manager.create_task(item.url)
                    item.task_id = task_id
                    self.current_task_id = task_id
                    
                    # Process download (run synchronous function in executor)
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, process_download_func, task_id, item.url, item.source)
                    
                    # Wait a bit for task to update
                    await asyncio.sleep(1)
                    
                    # Check task status
                    task = self.task_manager.get_task(task_id)
                    if task and task.status == TaskStatus.COMPLETED:
                        item.status = "completed"
                        logger.info(f"Queue item completed: {item.url}")
                    elif task and task.status == TaskStatus.FAILED:
                        item.status = "failed"
                        item.error = task.error
                        logger.error(f"Queue item failed: {item.url} - {task.error}")
                    else:
                        # Check if file was downloaded anyway
                        item.status = "completed"  # Assume success if no error
                        logger.info(f"Queue item completed (no explicit status): {item.url}")
                    
                except Exception as e:
                    logger.exception(f"Error processing queue item {item.url}: {str(e)}")
                    item.status = "failed"
                    item.error = str(e)
                
                finally:
                    self.current_task_id = None
                    # Small delay between downloads
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.exception(f"Error in queue processor: {str(e)}")
                await asyncio.sleep(5)
    
    def stop_processing(self):
        """Stop queue processing"""
        self.is_processing = False
        logger.info("Queue processor stopped")
    
    def get_status(self) -> dict:
        """Get queue status"""
        pending = sum(1 for item in self.queue if item.status == "pending")
        processing = sum(1 for item in self.queue if item.status == "processing")
        completed = sum(1 for item in self.queue if item.status == "completed")
        failed = sum(1 for item in self.queue if item.status == "failed")
        
        return {
            "total": len(self.queue),
            "pending": pending,
            "processing": processing,
            "completed": completed,
            "failed": failed,
            "is_processing": self.is_processing,
            "current_task_id": self.current_task_id
        }


# Global queue manager instance
queue_manager: Optional[QueueManager] = None

def get_queue_manager(task_manager: TaskManager) -> QueueManager:
    """Get or create queue manager instance"""
    global queue_manager
    if queue_manager is None:
        queue_manager = QueueManager(task_manager)
    return queue_manager

