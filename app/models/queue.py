"""Queue model for database"""
from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func
import enum
from app.database.db import Base
from app.models.track import SourceType


class QueueStatus(str, enum.Enum):
    """Queue item status enum"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class QueueItem(Base):
    """Queue item model for database"""
    __tablename__ = "queue_items"
    
    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False, index=True)
    source = Column(Enum(SourceType), nullable=True)
    task_id = Column(String, nullable=True, index=True)
    status = Column(Enum(QueueStatus), default=QueueStatus.PENDING, nullable=False, index=True)
    error = Column(String, nullable=True)
    title = Column(String, nullable=True)  # Track title if available
    progress = Column(Integer, default=0)  # Progress percentage
    message = Column(String, nullable=True)  # Status message
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return {
            "id": self.id,
            "url": self.url,
            "source": self.source.value if isinstance(self.source, SourceType) else self.source,
            "task_id": self.task_id,
            "status": self.status.value if isinstance(self.status, QueueStatus) else self.status,
            "error": self.error,
            "title": self.title,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }
    
    def __repr__(self):
        return f"<QueueItem(id={self.id}, url='{self.url}', status='{self.status}')>"
