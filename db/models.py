from sqlalchemy import Column, Integer, String, BigInteger, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    login = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    first_name = Column(String(100), nullable=True)
    registered_at = Column(DateTime, server_default=func.now())

    configs = relationship("ScreenerConfig", back_populates="user", cascade="all, delete")


class ScreenerConfig(Base):
    __tablename__ = "screener_configs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100), nullable=False)
    screener_type = Column(String(50), nullable=False)
    params = Column(JSON, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    user = relationship("User", back_populates="configs")