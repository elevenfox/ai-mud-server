from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Optional
from pydantic import BaseModel

from app.db.session import get_session
from app.core.engine import WorldEngine
from app.core.npc_agent import NPCAgent
from app.core.choice_generator import ChoiceGenerator
from app.core.judge import ActionJudge
from app.core.checkpoint import CheckpointManager
from app.models.schemas import (
    World, Location, Player, NPC, GameEvent,
    Choice, ChoicesResponse, ActionResult, JudgeResult
)

router = APIRouter()


# ============== Request Models ==============

class ActionRequest(BaseModel):
    world_id: str
    player_id: str
    action_text: str


class TalkRequest(BaseModel):
    world_id: str
    player_id: str
    npc_id: str
    message: str


class ChoiceSelectRequest(BaseModel):
    world_id: str
    player_id: str
    choice_id: str
    choices_context: List[Choice]  # 前端传回选项上下文


class CustomActionRequest(BaseModel):
    world_id: str
    player_id: str
    action_text: str


class CheckpointRequest(BaseModel):
    world_id: str
    player_id: str
    description: Optional[str] = None


# ============== World State Endpoints ==============

@router.get("/world/{world_id}/state")
async def get_world_state(
    world_id: str, 
    player_id: str, 
    session: AsyncSession = Depends(get_session)
):
    """获取当前世界状态（含选项）"""
    engine = WorldEngine(session)
    world, player, location, npcs = await engine.get_world_context(world_id, player_id)
    
    # 生成当前情境的选项
    choice_gen = ChoiceGenerator(session)
    choices_response = await choice_gen.generate_situation_choices(world_id, player_id)
    
    # 检查是否有 NPC 首次见面消息
    npc_agent = NPCAgent(session)
    first_messages = {}
    for npc in npcs:
        first_msg = await npc_agent.get_first_meeting_message(npc.id, world_id, player_id)
        if first_msg:
            first_messages[npc.id] = first_msg
    
    return {
        "world": {
            "id": world.id,
            "time": world.time,
            "name": world.name,
            "mood": world.current_mood,
            "flags": world.flags
        },
        "location": {
            "id": location.id,
            "name": location.name,
            "description": location.description,
            "background_url": location.background_url,
            "connections": location.connections
        },
        "npcs": [
            {
                "id": npc.id,
                "name": npc.name,
                "description": npc.description,
                "emotion": npc.current_emotion,
                "relationship": npc.relationship,
                "portrait_url": npc.portrait_url,
                "first_message": first_messages.get(npc.id),
                "position": npc.position  # left, center, right
            }
            for npc in npcs
        ],
        "player": {
            "id": player.id,
            "name": player.name,
            "inventory": player.inventory,
            "portrait_url": player.portrait_url,
            "personality": player.personality,
            "background": player.background,
        },
        "choices": choices_response
    }


@router.get("/world/{world_id}/events")
async def get_events(
    world_id: str,
    limit: int = 20,
    session: AsyncSession = Depends(get_session)
):
    """获取最近的游戏事件"""
    stmt = (
        select(GameEvent)
        .where(GameEvent.world_id == world_id)
        .order_by(GameEvent.timestamp.desc())
        .limit(limit)
    )
    results = await session.execute(stmt)
    events = results.scalars().all()
    
    return {
        "events": [
            {
                "id": e.id,
                "timestamp": e.timestamp,
                "event_type": e.event_type,
                "content": e.content,
                "extra_data": e.extra_data
            }
            for e in reversed(events)
        ]
    }


# ============== Action Endpoints ==============

@router.post("/action")
async def take_action(
    request: ActionRequest, 
    session: AsyncSession = Depends(get_session)
):
    """处理玩家行动（旧接口，保持兼容）"""
    engine = WorldEngine(session)
    result = await engine.process_action(
        request.world_id, 
        request.player_id, 
        request.action_text
    )
    if result.get("status") == "error":
        raise HTTPException(status_code=400, detail=result.get("message"))
    return result


@router.post("/choice/select", response_model=ActionResult)
async def select_choice(
    request: ChoiceSelectRequest,
    session: AsyncSession = Depends(get_session)
):
    """选择预设选项"""
    choice_gen = ChoiceGenerator(session)
    result = await choice_gen.execute_choice(
        request.world_id,
        request.player_id,
        request.choice_id,
        request.choices_context
    )
    return result


@router.post("/choice/custom", response_model=ActionResult)
async def custom_action(
    request: CustomActionRequest,
    session: AsyncSession = Depends(get_session)
):
    """执行自定义行动（经过 Judge 校验）"""
    judge = ActionJudge(session)
    result = await judge.execute_custom_action(
        request.world_id,
        request.player_id,
        request.action_text
    )
    return result


@router.post("/choice/judge", response_model=JudgeResult)
async def judge_action_endpoint(
    request: CustomActionRequest,
    session: AsyncSession = Depends(get_session)
):
    """仅校验行动是否合法（不执行）"""
    judge = ActionJudge(session)
    result = await judge.judge_custom_action(
        request.world_id,
        request.player_id,
        request.action_text
    )
    return result


# ============== NPC Endpoints ==============

@router.post("/npc/talk")
async def talk_to_npc(
    request: TalkRequest,
    session: AsyncSession = Depends(get_session)
):
    """与 NPC 对话"""
    agent = NPCAgent(session)
    result = await agent.talk_to_npc(
        request.world_id,
        request.player_id,
        request.npc_id,
        request.message
    )
    
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.get("/npc/{npc_id}")
async def get_npc(
    npc_id: str,
    session: AsyncSession = Depends(get_session)
):
    """获取 NPC 详情"""
    npc = await session.get(NPC, npc_id)
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    
    return {
        "id": npc.id,
        "name": npc.name,
        "description": npc.description,
        "personality": npc.personality,
        "emotion": npc.current_emotion,
        "relationship": npc.relationship,
        "portrait_url": npc.portrait_url,
        "location_id": npc.location_id
    }


# ============== Checkpoint Endpoints ==============

@router.post("/checkpoint/save")
async def save_checkpoint(
    request: CheckpointRequest,
    session: AsyncSession = Depends(get_session)
):
    """创建存档"""
    manager = CheckpointManager(session)
    checkpoint = await manager.create_checkpoint(
        request.world_id,
        request.player_id,
        request.description or "",
        is_auto=False
    )
    return {
        "success": True,
        "checkpoint_id": checkpoint.id,
        "description": checkpoint.description,
        "created_at": checkpoint.created_at.isoformat()
    }


@router.post("/checkpoint/{checkpoint_id}/load")
async def load_checkpoint(
    checkpoint_id: str,
    session: AsyncSession = Depends(get_session)
):
    """加载存档"""
    manager = CheckpointManager(session)
    result = await manager.load_checkpoint(checkpoint_id)
    
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    
    return result


@router.get("/checkpoint/list")
async def list_checkpoints(
    world_id: str,
    player_id: str,
    include_auto: bool = True,
    session: AsyncSession = Depends(get_session)
):
    """列出所有存档"""
    manager = CheckpointManager(session)
    checkpoints = await manager.list_checkpoints(world_id, player_id, include_auto)
    return {"checkpoints": checkpoints}


@router.delete("/checkpoint/{checkpoint_id}")
async def delete_checkpoint(
    checkpoint_id: str,
    session: AsyncSession = Depends(get_session)
):
    """删除存档"""
    manager = CheckpointManager(session)
    success = await manager.delete_checkpoint(checkpoint_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    
    return {"success": True}


# ============== Health Check ==============

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}
