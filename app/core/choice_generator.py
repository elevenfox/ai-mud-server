"""选项生成系统 - 在关键节点生成玩家选项"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Dict, Any
import time

from app.models.schemas import (
    World, Location, Player, NPC, GameEvent, 
    Choice, ChoicesResponse, ActionResult
)
from app.core.ai import generate_choices, generate_narrative, generate_json, generate_json


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
        
        # 玩家状态（包含经济系统）
        player_stats = {
            "name": player.name,
            "location": location.name,
            "inventory": player.inventory,
            "relationships": {
                n.name: n.relationship for n in npcs
            },
            "currency": player.currency,
            "gems": player.gems,
        }
        
        # 构建 NPC 信息列表（传给 AI 决定位置）
        npcs_in_scene = [
            {"id": npc.id, "name": npc.name, "emotion": npc.current_emotion}
            for npc in npcs
        ]
        
        # 构建经济系统信息
        economy_info = f"""
经济系统:
- {world.currency_name}: {player.currency}（游戏内货币）
- {world.gem_name}: {player.gems}（付费货币）
{f'- 货币规则: {world.currency_rules}' if world.currency_rules else ''}
基本价值单位: 1 {world.currency_name} = 一顿普通饭的价值
"""
        
        # AI 生成选项（包括角色位置）
        result = await generate_choices(
            world_rules=world.rules or [],
            current_situation=current_situation + economy_info,
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
        
        # 构建经济系统信息
        economy_info = f"""
经济系统:
- {world.currency_name}: {player.currency}（游戏内货币）
- {world.gem_name}: {player.gems}（付费货币）
{f'- 货币规则: {world.currency_rules}' if world.currency_rules else ''}
基本价值单位: 1 {world.currency_name} = 一顿普通饭的价值
任务报酬参考：简单任务 10-30，中等任务 50-100，困难任务 150-300
打工报酬：按时间计算，1 小时约 20-50 货币
"""

        # 生成选择的结果叙事（包含货币变化）
        system_prompt = """你是一个 MUD 游戏的叙事者。请用中文回复。
描述玩家选择选项后发生的事。
要生动但简洁，包含感官细节。
叙事应该自然地从选择中展开。

经济系统：
- 如果玩家完成了任务、打工、寻宝等，给予适当的货币奖励
- 如果玩家消费了（购买、支付等），扣除相应的货币
- 基本价值单位：1 货币 = 1 顿普通饭的价值
- 任务报酬参考：简单任务 10-30，中等任务 50-100，困难任务 150-300
- 打工报酬：按时间计算，1 小时约 20-50 货币

用 JSON 格式回复:
{
    "narrative": "叙事文本",
    "currency_change": 0,  // 货币变化（正数=获得，负数=消费）
    "gems_change": 0,      // 宝石变化（通常为 0，除非特殊奖励）
    "reason": "货币变化的原因（可选）"
}"""

        user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in (world.rules or []))}

当前地点: {location.name} - {location.description}
{economy_info}
最近事件:
{chr(10).join(recent_events[-3:])}

玩家的选择: {selected.text}

描述这个选择的结果，并判断是否需要给予货币奖励或扣除货币。"""

        # 使用 generate_json 获取结构化结果（包含货币变化）
        result = await generate_json(system_prompt, user_prompt)
        narrative = result.get("narrative", "你执行了这个选择...")
        currency_change = result.get("currency_change", 0)
        gems_change = result.get("gems_change", 0)
        
        # 更新玩家货币
        if currency_change != 0:
            player.currency = max(0, player.currency + currency_change)
            self.session.add(player)
        
        if gems_change != 0:
            player.gems = max(0, player.gems + gems_change)
            self.session.add(player)
        
        # 记录事件
        event = GameEvent(
            world_id=world_id,
            timestamp=int(time.time()),
            event_type="choice",
            content=narrative,
            extra_data={
                "choice_id": choice_id,
                "choice_text": selected.text,
                "mood": world.current_mood,
                "currency_change": currency_change,
                "gems_change": gems_change
            }
        )
        self.session.add(event)
        await self.session.commit()
        
        return ActionResult(
            success=True,
            narrative=narrative,
            mood=world.current_mood,
            currency_change=currency_change,
            gems_change=gems_change
        )
