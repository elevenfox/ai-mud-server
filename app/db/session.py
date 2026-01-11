import os
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import SQLModel
from dotenv import load_dotenv

# 确保所有模型被注册到 SQLModel.metadata
from app.models.schemas import (
    World, Location, NPC, Player, GameEvent, 
    Conversation, Checkpoint, CharacterTemplate, LocationTemplate
)

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./world.db")

engine = create_async_engine(DATABASE_URL, echo=True, future=True)

async def init_db():
    async with engine.begin() as conn:
        # 在 Phase 1 中，我们每次启动时可以根据需要创建表
        # 注意：SQLModel.metadata.create_all 需要同步 engine，
        # 在异步环境下需要使用 run_sync
        await conn.run_sync(SQLModel.metadata.create_all)

async def get_session() -> AsyncSession:
    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
