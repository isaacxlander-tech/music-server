"""Task manager for tracking download progress"""
import uuid
import logging
from typing import Dict, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status enum"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskInfo:
    """Information about a download task"""
    def __init__(self, task_id: str, url: str):
        self.task_id = task_id
        self.url = url
        self.status = TaskStatus.PENDING
        self.progress = 0
        self.message = "Initialisation..."
        self.error: Optional[str] = None
        self.track_id: Optional[int] = None
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "url": self.url,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "track_id": self.track_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }


class TaskManager:
    """Manages download tasks and their progress"""
    
    def __init__(self):
        self.tasks: Dict[str, TaskInfo] = {}
    
    def create_task(self, url: str) -> str:
        """Create a new download task"""
        task_id = str(uuid.uuid4())
        task = TaskInfo(task_id, url)
        self.tasks[task_id] = task
        logger.info(f"Created task {task_id} for URL: {url}")
        return task_id
    
    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task information"""
        return self.tasks.get(task_id)
    
    def update_task(self, task_id: str, status: Optional[TaskStatus] = None, 
                   progress: Optional[int] = None, message: Optional[str] = None,
                   error: Optional[str] = None, track_id: Optional[int] = None):
        """Update task information"""
        task = self.tasks.get(task_id)
        if not task:
            logger.warning(f"Task {task_id} not found")
            return
        
        if status:
            task.status = status
        if progress is not None:
            task.progress = max(0, min(100, progress))  # Clamp between 0 and 100
        if message:
            task.message = message
        if error:
            task.error = error
            task.status = TaskStatus.FAILED
        if track_id:
            task.track_id = track_id
        
        task.updated_at = datetime.now()
        logger.debug(f"Updated task {task_id}: {task.status.value} - {task.progress}% - {task.message}")
    
    def delete_task(self, task_id: str):
        """Delete a task (cleanup)"""
        if task_id in self.tasks:
            del self.tasks[task_id]
            logger.info(f"Deleted task {task_id}")
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Clean up old completed/failed tasks"""
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        
        to_delete = [
            task_id for task_id, task in self.tasks.items()
            if task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED] 
            and task.updated_at < cutoff
        ]
        
        for task_id in to_delete:
            self.delete_task(task_id)
        
        if to_delete:
            logger.info(f"Cleaned up {len(to_delete)} old tasks")


# Global task manager instance
task_manager = TaskManager()

