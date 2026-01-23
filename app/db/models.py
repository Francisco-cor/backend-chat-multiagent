from sqlalchemy import Column, Integer, String, Text, DateTime, Index, Boolean
from sqlalchemy.sql import func
from app.db.base import Base

class ConversationHistory(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" or "model"
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Composite index to speed up searches by session and date
    __table_args__ = (Index('ix_session_id_timestamp', "session_id", "timestamp"),)

    def __repr__(self):
        return f"<ConversationHistory(session_id='{self.session_id}', role='{self.role}')>"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean(), default=True)

    def __repr__(self):
        return f"<User(email='{self.email}')>"