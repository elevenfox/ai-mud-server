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
from app.core.npc_manager import NPCManager, spawn_npcs_for_scene
from app.models.schemas import (
    World, Location, Player, NPC, GameEvent, CharacterTemplate,
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


# ============== Helper Functions ==============

async def _get_npc_display_data(npc: NPC, session: AsyncSession) -> dict:
    """
    获取 NPC 的显示数据，优先从模板获取（如果有 template_id）
    这样修改模板后，NPC 数据会自动更新
    """
    # 如果有 template_id，从模板获取最新数据
    if npc.template_id:
        template = await session.get(CharacterTemplate, npc.template_id)
        if template:
            return {
                "name": template.name,  # 优先使用模板的名字
                "description": template.description,
                "personality": template.personality,
                "portrait_url": template.portrait_path,
                "first_message": template.first_message,
                "scenario": template.scenario,
                "example_dialogs": template.example_dialogs or [],
            }
    
    # 没有 template_id 或模板不存在，使用 NPC 自身的数据
    return {
        "name": npc.name,
        "description": npc.description,
        "personality": npc.personality,
        "portrait_url": npc.portrait_url,
        "first_message": npc.first_message,
        "scenario": npc.scenario,
        "example_dialogs": npc.example_dialogs or [],
    }


async def _build_npc_list(
    npcs: List[NPC],
    session: AsyncSession,
    first_messages: dict,
    character_positions: dict
) -> List[dict]:
    """构建 NPC 列表，从模板动态获取数据"""
    result = []
    for npc in npcs:
        display_data = await _get_npc_display_data(npc, session)
        result.append({
            "id": npc.id,
            "name": display_data["name"],
            "description": display_data["description"],
            "portrait_url": display_data["portrait_url"],
            # 运行时状态（始终从 NPC 实例获取）
            "emotion": npc.current_emotion,
            "relationship": npc.relationship,
            "first_message": first_messages.get(npc.id) or display_data.get("first_message"),
            # 优先使用 AI 决定的位置，否则用数据库中的默认值
            "position": character_positions.get(npc.id, npc.position)
        })
    return result


def _calculate_player_position(npcs: List[NPC]) -> str:
    """
    根据当前场景的 NPC 位置，动态决定玩家立绘位置。
    
    简单逻辑：
    - 如果有 NPC 在右边，玩家在左边
    - 如果有 NPC 在左边但右边没有，玩家在右边
    - 如果 NPC 都在中间，玩家在右边
    - 没有 NPC，玩家在右边
    
    后续可以让 AI 根据剧情智能决定位置。
    """
    if not npcs:
        return "right"
    
    npc_positions = [npc.position for npc in npcs]
    
    # 如果右边有 NPC，玩家去左边
    if "right" in npc_positions:
        return "left"
    # 如果左边有 NPC，玩家去右边
    elif "left" in npc_positions:
        return "right"
    # NPC 在中间，玩家去右边
    else:
        return "right"


# ============== World State Endpoints ==============

@router.get("/world/{world_id}/state")
async def get_world_state(
    world_id: str, 
    player_id: str, 
    session: AsyncSession = Depends(get_session)
):
    """获取当前世界状态（含选项）- 支持动态 NPC 加载"""
    engine = WorldEngine(session)
    world, player, location, existing_npcs = await engine.get_world_context(world_id, player_id)
    
    # ====== 动态 NPC 加载 ======
    # 如果场景没有 NPC，尝试根据场景和剧情动态生成
    npc_manager = NPCManager(session)
    
    # 构建故事上下文（用于 AI 判断需要什么角色）
    story_context = f"玩家 {player.name} 进入了 {location.name}。{location.description}"
    
    # 获取场景 NPC（可能触发动态创建）
    npcs = await npc_manager.get_scene_npcs(
        world_id=world_id,
        location_id=location.id,
        story_context=story_context if not existing_npcs else "",  # 只有无 NPC 时才触发
        player_id=player_id
    )
    # ====== 动态 NPC 加载结束 ======
    
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
    
    # 从 AI 生成的选项中获取角色位置
    character_positions = choices_response.character_positions or {}
    
    # 如果 AI 没有返回位置，使用默认逻辑
    player_position = character_positions.get("player", _calculate_player_position(npcs))
    
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
        "npcs": await _build_npc_list(npcs, session, first_messages, character_positions),
        "player": {
            "id": player.id,
            "name": player.name,
            "inventory": player.inventory,
            "portrait_url": player.portrait_url,
            "personality": player.personality,
            "background": player.background,
            # 优先使用 AI 决定的位置
            "position": player_position,
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


# ============== NPC Management Endpoints ==============

@router.post("/npc/spawn")
async def spawn_npc_for_scene(
    world_id: str,
    location_id: str,
    story_context: str = "",
    session: AsyncSession = Depends(get_session)
):
    """
    手动触发场景 NPC 生成
    
    用于：
    - 剧情需要特定角色出场
    - 测试 NPC 动态生成功能
    """
    manager = NPCManager(session)
    npcs = await manager.get_scene_npcs(
        world_id=world_id,
        location_id=location_id,
        story_context=story_context or "需要为这个场景添加适合的角色"
    )
    
    return {
        "success": True,
        "npcs": [
            {
                "id": npc.id,
                "name": npc.name,
                "description": npc.description,
                "portrait_url": npc.portrait_url,
                "is_new": npc.id.startswith("npc_")  # 新创建的 NPC
            }
            for npc in npcs
        ]
    }


@router.post("/npc/{npc_id}/move")
async def move_npc(
    npc_id: str,
    location_id: str,
    session: AsyncSession = Depends(get_session)
):
    """移动 NPC 到新场景"""
    manager = NPCManager(session)
    success = await manager.move_npc(npc_id, location_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="NPC not found")
    
    return {"success": True}


@router.post("/npc/{npc_id}/update")
async def update_npc(
    npc_id: str,
    emotion: Optional[str] = None,
    relationship_change: int = 0,
    position: Optional[str] = None,
    session: AsyncSession = Depends(get_session)
):
    """更新 NPC 状态（情绪、关系、位置）"""
    manager = NPCManager(session)
    npc = await manager.update_npc_state(
        npc_id=npc_id,
        emotion=emotion,
        relationship_change=relationship_change,
        position=position
    )
    
    if not npc:
        raise HTTPException(status_code=404, detail="NPC not found")
    
    return {
        "id": npc.id,
        "name": npc.name,
        "emotion": npc.current_emotion,
        "relationship": npc.relationship,
        "position": npc.position
    }


# ============== Health Check ==============

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}
