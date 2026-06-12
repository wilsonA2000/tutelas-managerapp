"""Servicio de autenticación JWT."""

import secrets
from pathlib import Path
from backend.core.time import utcnow
from datetime import datetime, timedelta

from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.auth.models import User
from backend.core.settings import settings


def _load_or_create_secret() -> str:
    """Secreto JWT persistente cuando .env no define JWT_SECRET (P17/C5).

    Antes se regeneraba en CADA arranque (`secrets.token_hex` en import) →
    todas las sesiones morían al reiniciar el backend. Ahora se genera una
    vez y se guarda en data/.jwt_secret (0600).
    """
    secret_file = Path(__file__).resolve().parent.parent.parent / "data" / ".jwt_secret"
    try:
        if secret_file.is_file():
            stored = secret_file.read_text().strip()
            if len(stored) >= 32:
                return stored
        secret = secrets.token_hex(32)
        secret_file.parent.mkdir(parents=True, exist_ok=True)
        secret_file.write_text(secret)
        secret_file.chmod(0o600)
        return secret
    except OSError:
        # Filesystem de solo lectura u otro fallo: degradar al comportamiento
        # anterior (secreto efímero) antes que impedir el arranque.
        return secrets.token_hex(32)


# Configuración JWT
JWT_SECRET = settings.JWT_SECRET or _load_or_create_secret()
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 8
REFRESH_TOKEN_EXPIRE_DAYS = 30

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: int, username: str) -> str:
    expire = utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": str(user_id), "username": username, "exp": expire, "type": "access"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    expire = utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except JWTError:
        return None


def authenticate_user(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return None
    user.last_login = utcnow()
    db.commit()
    return user


def create_default_user(db: Session) -> User | None:
    """Crear usuario admin por defecto si no existe ninguno."""
    if db.query(User).count() > 0:
        return None
    user = User(
        username="wilson",
        password_hash=hash_password("tutelas2026"),
        full_name="Wilson - Gobernación de Santander",
        role="admin",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
