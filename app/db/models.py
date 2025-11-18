from sqlalchemy import Column, Integer, String, Text, DateTime, Index
from sqlalchemy.sql import func
from app.db.base import Base

class ConversationHistory(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" o "model"
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # Índice compuesto para acelerar las búsquedas por sesión y fecha
    __table_args__ = (Index('ix_session_id_timestamp', "session_id", "timestamp"),)

    def __repr__(self):
        return f"<ConversationHistory(session_id='{self.session_id}', role='{self.role}')>"