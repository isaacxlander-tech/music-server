"""Track model for database"""
from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func
import enum
from app.database.db import Base


class SourceType(str, enum.Enum):
    """Source types for downloads"""
    YOUTUBE = "youtube"
    SPOTIFY = "spotify"
    UNKNOWN = "unknown"


class Track(Base):
    """Track model"""
    __tablename__ = "tracks"
    
    id = Column(Integer, primary_key=True, index=True)
    artist = Column(String, nullable=False, index=True)
    album = Column(String, nullable=True, index=True)
    title = Column(String, nullable=False, index=True)
    year = Column(Integer, nullable=True)
    genre = Column(String, nullable=True)
    duration = Column(Integer, nullable=True)  # Duration in seconds
    file_path = Column(String, nullable=False, unique=True)
    file_size = Column(Integer, nullable=True)  # File size in bytes
    source = Column(Enum(SourceType), default=SourceType.UNKNOWN)
    source_url = Column(String, nullable=True)
    downloaded_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<Track(id={self.id}, artist='{self.artist}', title='{self.title}')>"

