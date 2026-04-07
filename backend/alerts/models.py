"""Modelo de alertas proactivas."""

from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime

from backend.database.models import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_id = Column(Integer, nullable=True, index=True)
    alert_type = Column(String, nullable=False, index=True)
    # Types: DEADLINE, DUPLICATE_DOC, MISSING_DOC, ANOMALY, UNMATCHED_EMAIL, EXTRACTION_ERROR
    severity = Column(String, nullable=False, default="WARNING")
    # Severity: INFO, WARNING, CRITICAL
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="NEW", index=True)
    # Status: NEW, SEEN, DISMISSED, RESOLVED
    created_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime, nullable=True)
