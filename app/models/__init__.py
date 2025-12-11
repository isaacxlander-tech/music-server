"""Models package"""
# Import models to register them with SQLAlchemy Base
from app.models import track, user

__all__ = ['track', 'user']
