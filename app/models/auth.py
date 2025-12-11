"""Authentication models and utilities"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import secrets
import hashlib
from sqlalchemy.orm import Session
from app.models.user import User, Token as TokenModel


class LoginRequest(BaseModel):
    """Login request model"""
    username: str
    password: str


class TokenResponse(BaseModel):
    """Token response model"""
    access_token: str
    token_type: str = "bearer"


def hash_password(password: str) -> str:
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against hash"""
    return hash_password(password) == password_hash


def create_token(db: Session, user_id: int) -> str:
    """Create a new access token and store in database"""
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now() + timedelta(days=7)
    
    db_token = TokenModel(
        token=token,
        user_id=user_id,
        expires_at=expires_at
    )
    db.add(db_token)
    db.commit()
    
    return token


def verify_token(db: Session, token: str) -> Optional[int]:
    """Verify token and return user_id if valid"""
    db_token = db.query(TokenModel).filter(TokenModel.token == token).first()
    
    if not db_token:
        return None
    
    if datetime.now() > db_token.expires_at:
        # Token expired, delete it
        db.delete(db_token)
        db.commit()
        return None
    
    return db_token.user_id


def get_user_by_username(db: Session, username: str) -> Optional[User]:
    """Get user by username"""
    return db.query(User).filter(User.username == username).first()


def authenticate_user(db: Session, username: str, password: str) -> Optional[User]:
    """Authenticate user and return User if valid"""
    user = get_user_by_username(db, username)
    
    if not user:
        return None
    
    if not user.is_active:
        return None
    
    if not verify_password(password, user.password_hash):
        return None
    
    return user


def delete_token(db: Session, token: str) -> bool:
    """Delete a token from database"""
    db_token = db.query(TokenModel).filter(TokenModel.token == token).first()
    if db_token:
        db.delete(db_token)
        db.commit()
        return True
    return False
