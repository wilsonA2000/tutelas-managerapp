"""Modelo de usuario para autenticación."""

from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime

from backend.database.models import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    full_name = Column(String, default="")
    role = Column(String, default="admin")  # admin | viewer (futuro)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
