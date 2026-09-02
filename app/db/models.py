from sqlalchemy import Column, Integer, String, Text, DateTime, Index, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base import Base

class ConversationHistory(Base):
    __tablename__ = "conversation_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)  # "user" or "model"
    content = Column(Text, nullable=False)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Composite indexes for efficient history queries
    __table_args__ = (
        Index('ix_session_id_timestamp', "session_id", "timestamp"),
        Index('ix_conv_history_user_session', "user_id", "session_id", "timestamp"),
    )

    def __repr__(self):
        return f"<ConversationHistory(session_id='{self.session_id}', role='{self.role}')>"

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean(), default=True)
    failed_login_attempts = Column(Integer, default=0, nullable=False, server_default="0")
    locked_until = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self):
        return f"<User(email='{self.email}')>"


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    def __repr__(self):
        return f"<RevokedToken(jti='{self.jti}')>"


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    model = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True, index=True)
    total_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    total_cost_usd = Column(Float, nullable=False, default=0.0, server_default="0")
    legacy_session_id = Column(String, nullable=True, index=True)

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
        Index("ix_conversations_user_session", "user_id", "legacy_session_id"),
    )

    def __repr__(self):
        return f"<Conversation(id={self.id}, user_id={self.user_id}, title={self.title})>"


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)  # user / model / system / tool
    content = Column(Text, nullable=False)
    tokens = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    legacy_session_id = Column(String, nullable=True)

    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    def __repr__(self):
        return f"<Message(id={self.id}, conv={self.conversation_id}, role={self.role})>"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    source = Column(String, nullable=True)  # filename or url
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    total_chunks = Column(Integer, nullable=False, default=0, server_default="0")

    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (Index("ix_documents_user_created", "user_id", "created_at"),)

    def __repr__(self):
        return f"<Document(id={self.id}, title={self.title})>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    # For SQLite compat store as JSON text; for PG with pgvector use Vector(1536)
    # We store as TEXT containing JSON array; vector search done in Python fallback
    embedding = Column(Text, nullable=True)
    token_count = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="chunks")

    __table_args__ = (
        Index("ix_chunks_document_index", "document_id", "chunk_index"),
        Index("ix_chunks_document_id", "document_id"),
    )

    def __repr__(self):
        return f"<DocumentChunk(id={self.id}, doc={self.document_id}, idx={self.chunk_index})>"