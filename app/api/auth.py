"""Authentication routes"""
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional
from sqlalchemy.orm import Session
from app.database.db import get_db
from app.models.auth import (
    LoginRequest, 
    TokenResponse,
    authenticate_user,
    create_token,
    verify_token,
    delete_token,
    get_user_by_username
)
from app.models.user import User

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Login endpoint
    
    Default credentials:
    - Username: admin
    - Password: admin
    """
    user = authenticate_user(db, credentials.username, credentials.password)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    token = create_token(db, user.id)
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Logout endpoint"""
    if not authorization:
        return {"message": "No token provided"}
    
    try:
        token = authorization.replace("Bearer ", "")
        if delete_token(db, token):
            return {"message": "Logged out successfully"}
        return {"message": "Token not found"}
    except Exception as e:
        return {"message": f"Logout error: {str(e)}"}


@router.get("/me")
async def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """Get current user info"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        user_id = verify_token(db, token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        
        return {
            "username": user.username,
            "email": user.email,
            "is_admin": user.is_admin,
            "id": user.id
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")


def get_current_user_id(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
) -> int:
    """Dependency to get current user ID from token"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    try:
        token = authorization.replace("Bearer ", "")
        user_id = verify_token(db, token)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        return user_id
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
