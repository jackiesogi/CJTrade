from datetime import datetime
from datetime import timedelta
from typing import Optional

from cjtrade.apps.FinHub import database
from cjtrade.apps.FinHub import models
from cjtrade.apps.FinHub.config import settings
from cjtrade.pkgs.logger import get_logger
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt
from jose import JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
# One source for the signing key. This module used to read os.getenv itself
# with its own fallback ("insecure-default-key-change-me"), different from the
# one in config.py, so the key actually in use depended on which module you
# read. config.py now has no fixed fallback at all.

log = get_logger("FinHub.auth")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def hash_password(password: str) -> str:
    """Bcrypt hash of a plaintext password."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_user(token: str = Depends(oauth2_scheme),
                     db: Session = Depends(database.get_db)):
    """Validate the bearer token and return the User.

    Every route that reaches the broker or starts a process depends on this.
    Worth being explicit about why: an unauthenticated POST /api/v1/runs would
    let anything that can reach this port spawn processes on the machine, and
    an unauthenticated order route would let it trade.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY,
                             algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.username == username).first()
    if user is None:
        raise credentials_exception
    return user
