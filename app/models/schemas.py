"""Pydantic schemas for API"""
from pydantic import BaseModel, HttpUrl
from datetime import datetime
from typing import Optional, List
from app.models.track import SourceType


class TrackBase(BaseModel):
    """Base track schema"""
    artist: str
    album: Optional[str] = None
    title: str
    year: Optional[int] = None
    genre: Optional[str] = None
    duration: Optional[int] = None
    source: SourceType = SourceType.UNKNOWN


class TrackCreate(TrackBase):
    """Schema for creating a track"""
    file_path: str
    file_size: Optional[int] = None
    source_url: Optional[str] = None


class TrackResponse(TrackBase):
    """Schema for track response"""
    id: int
    file_path: str
    file_size: Optional[int] = None
    source_url: Optional[str] = None
    downloaded_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True  # Pydantic v2 uses from_attributes instead of from_orm


class DownloadRequest(BaseModel):
    """Schema for download request"""
    url: str
    source: Optional[SourceType] = None  # Auto-detect if not provided


class DownloadResponse(BaseModel):
    """Schema for download response"""
    success: bool
    message: str
    track: Optional[TrackResponse] = None


class SearchQuery(BaseModel):
    """Schema for search query"""
    query: str
    artist: Optional[str] = None
    album: Optional[str] = None
    title: Optional[str] = None


class QueueAddRequest(BaseModel):
    """Schema for adding URL to queue"""
    url: str
    source: Optional[SourceType] = None
    title: Optional[str] = None  # Track title if available


class QueueAddMultipleRequest(BaseModel):
    """Schema for adding multiple URLs to queue"""
    urls: List[str]
    source: Optional[SourceType] = None
    titles: Optional[List[str]] = None  # Track titles if available (same order as urls)


class AlbumExtractRequest(BaseModel):
    """Schema for extracting album/playlist URLs"""
    url: str

