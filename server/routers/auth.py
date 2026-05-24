# server/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.auth import verify_password, create_access_token, get_current_user
from server.database import get_db
from server.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: int
    username: str
    is_active: bool
    is_admin: bool = False

    model_config = {"from_attributes": True}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号已被禁用")
    return TokenResponse(access_token=create_access_token(user.username))


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/users/search", response_model=list[UserOut])
def search_users(
    q: str = "",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fuzzy search users by username (for sharing). Excludes caller."""
    query = db.query(User).filter(User.is_active == True, User.id != current_user.id)
    if q.strip():
        query = query.filter(User.username.ilike(f"%{q.strip()}%"))
    return query.order_by(User.username).limit(20).all()
