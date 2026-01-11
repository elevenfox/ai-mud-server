"""选项生成系统 - 在关键节点生成玩家选项"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Dict, Any
import time

from app.models.schemas import (
    World, Location, Player, NPC, GameEvent, 
    Choice, ChoicesResponse, ActionResult
)
from app.core.ai import generate_choices, generate_narrative


class ChoiceGenerator:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_recent_events(self, world_id: str, limit: int = 10) -> List[str]:
        """获取最近的游戏事件"""
        statement = (
            select(GameEvent)
            .where(GameEvent.world_id == world_id)
            .order_by(GameEvent.timestamp.desc())
            .limit(limit)
        )
        results = await self.session.execute(statement)
        events = results.scalars().all()
        return [f"[{e.event_type}] {e.content[:100]}" for e in reversed(events)]
    
    async def get_available_actions(self, location: Location, npcs: List[NPC]) -> List[str]:
        """根据当前环境获取可用的物理行动"""
        actions = []
        
        # 移动选项
        if location.connections:
            actions.append(f"Move to connected locations: {', '.join(location.connections)}")
        
        # 与 NPC 交互
        for npc in npcs:
            actions.append(f"Talk to {npc.name}")
        
        # 通用动作
        actions.extend([
            "Look around / Observe the environment",
            "Check inventory",
            "Wait / Pass time"
        ])
        
        return actions
    
    async def generate_situation_choices(
        self,
        world_id: str,
        player_id: str,
        situation_description: str = ""
    ) -> ChoicesResponse:
        """生成当前情境的选项"""
        # 获取上下文
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        location = await self.session.get(Location, player.location_id)
        
        # 获取当前地点的 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs = results.scalars().all()
        
        # 获取最近事件
        recent_events = await self.get_recent_events(world_id)
        
        # 获取可用行动
        available_actions = await self.get_available_actions(location, npcs)
        
        # 构建当前情境
        current_situation = situation_description or f"""
Location: {location.name}
Description: {location.description}
NPCs present: {', '.join([n.name for n in npcs]) or 'None'}
Player inventory: {', '.join(player.inventory) or 'Empty'}
World flags: {world.flags}
"""
        
        # 玩家状态
        player_stats = {
            "name": player.name,
            "location": location.name,
            "inventory": player.inventory,
            "relationships": {
                n.name: n.relationship for n in npcs
            }
        }
        
        # 构建 NPC 信息列表（传给 AI 决定位置）
        npcs_in_scene = [
            {"id": npc.id, "name": npc.name, "emotion": npc.current_emotion}
            for npc in npcs
        ]
        
        # AI 生成选项（包括角色位置）
        result = await generate_choices(
            world_rules=world.rules or [],
            current_situation=current_situation,
            recent_events=recent_events,
            player_stats=player_stats,
            available_actions=available_actions,
            npcs_in_scene=npcs_in_scene
        )
        
        # 解析结果
        choices = [
            Choice(
                id=c.get("id", str(i+1)),
                text=c.get("text", "Unknown option"),
                hint=c.get("hint")
            )
            for i, c in enumerate(result.get("choices", []))
        ]
        
        # 获取 AI 生成的角色位置
        character_positions = result.get("character_positions", {})
        
        return ChoicesResponse(
            narrative=result.get("narrative", "You consider your options..."),
            choices=choices,
            allow_custom=True,
            mood=result.get("mood", world.current_mood),
            character_positions=character_positions
        )
    
    async def execute_choice(
        self,
        world_id: str,
        player_id: str,
        choice_id: str,
        choices_context: List[Choice]
    ) -> ActionResult:
        """执行玩家选择的选项"""
        # 找到选中的选项
        selected = None
        for choice in choices_context:
            if choice.id == choice_id:
                selected = choice
                break
        
        if not selected:
            return ActionResult(
                success=False,
                narrative="Invalid choice.",
                mood="neutral"
            )
        
        # 获取上下文
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        location = await self.session.get(Location, player.location_id)
        
        # 获取最近事件
        recent_events = await self.get_recent_events(world_id)
        
        # 生成选择的结果叙事
        system_prompt = """You are the narrator for a MUD game. 
Describe what happens when the player makes their choice.
Be vivid but concise. Include sensory details.
The narrative should flow naturally from the choice."""

        user_prompt = f"""WORLD RULES:
{chr(10).join(f'- {rule}' for rule in (world.rules or []))}

CURRENT LOCATION: {location.name} - {location.description}

RECENT EVENTS:
{chr(10).join(recent_events[-3:])}

PLAYER'S CHOICE: {selected.text}

Narrate what happens next. Keep it to 2-3 paragraphs."""

        narrative = await generate_narrative(system_prompt, user_prompt)
        
        # 记录事件
        event = GameEvent(
            world_id=world_id,
            timestamp=int(time.time()),
            event_type="choice",
            content=narrative,
            extra_data={
                "choice_id": choice_id,
                "choice_text": selected.text,
                "mood": world.current_mood
            }
        )
        self.session.add(event)
        await self.session.commit()
        
        return ActionResult(
            success=True,
            narrative=narrative,
            mood=world.current_mood
        )
