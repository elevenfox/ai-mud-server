"""Judge 模块 - 校验玩家自由输入是否符合世界规则"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Dict, Any
import time

from app.models.schemas import World, Location, Player, NPC, GameEvent, JudgeResult, ActionResult
from app.core.ai import judge_action, generate_narrative


class ActionJudge:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_physical_constraints(self, location: Location, player: Player, npcs: List[NPC]) -> List[str]:
        """获取当前环境的物理约束"""
        constraints = [
            f"Player is in {location.name}",
            f"Player inventory: {', '.join(player.inventory) or 'empty'}",
        ]
        
        if location.connections:
            constraints.append(f"Connected locations: {', '.join(location.connections)}")
        else:
            constraints.append("No exits from current location")
        
        if npcs:
            constraints.append(f"NPCs present: {', '.join([n.name for n in npcs])}")
        else:
            constraints.append("No NPCs present")
        
        return constraints
    
    async def build_situation_context(
        self,
        world: World,
        location: Location,
        player: Player,
        npcs: List[NPC]
    ) -> str:
        """构建当前情境描述"""
        return f"""LOCATION: {location.name}
{location.description}

ATMOSPHERE: {world.current_mood}

PLAYER: {player.name}
Inventory: {', '.join(player.inventory) or 'Empty'}

NPCS HERE:
{chr(10).join([f'- {n.name}: {n.description} (Feeling: {n.current_emotion})' for n in npcs]) or 'None'}

WORLD FLAGS: {world.flags}"""

    async def judge_custom_action(
        self,
        world_id: str,
        player_id: str,
        action_text: str
    ) -> JudgeResult:
        """校验玩家的自由输入"""
        # 获取上下文
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        location = await self.session.get(Location, player.location_id)
        
        # 获取当前地点的 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs = list(results.scalars().all())
        
        # 获取物理约束
        physical_constraints = await self.get_physical_constraints(location, player, npcs)
        
        # 构建情境描述
        situation = await self.build_situation_context(world, location, player, npcs)
        
        # AI 判断
        result = await judge_action(
            world_rules=world.rules or [],
            current_situation=situation,
            player_action=action_text,
            physical_constraints=physical_constraints
        )
        
        return JudgeResult(
            allowed=result.get("allowed", True),
            reason=result.get("reason"),
            suggested_action=result.get("suggested_action")
        )
    
    async def execute_custom_action(
        self,
        world_id: str,
        player_id: str,
        action_text: str
    ) -> ActionResult:
        """执行经过校验的自定义行动"""
        # 先进行 Judge 校验
        judge_result = await self.judge_custom_action(world_id, player_id, action_text)
        
        if not judge_result.allowed:
            return ActionResult(
                success=False,
                narrative=f"你无法这样做。{judge_result.reason or ''}",
                choices=None,
                mood="neutral"
            )
        
        # 获取上下文
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        location = await self.session.get(Location, player.location_id)
        
        # 获取当前地点的 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs = list(results.scalars().all())
        
        # 生成行动结果叙事
        situation = await self.build_situation_context(world, location, player, npcs)
        
        system_prompt = """你是一个 MUD 游戏的叙事者。请用中文回复。
玩家执行了一个自定义行动，请描述发生了什么。
要有创意，但要遵守世界规则。
包含后果、NPC 的反应（如果相关）以及感官细节。

玩家输入格式说明：
- *星号包裹* = 动作或场景描写
- "双引号" = 角色说的话
- （圆括号）= 玩家意图/OOC指令
- ~波浪号~ = 拖长音或特殊语气
- **双星号** = 重点强调

你的回复格式：
- 用第二人称描述玩家的行动和结果（"你..."）
- 用 *星号* 包裹动作和场景描写
- 用 "引号" 包裹对话
- NPC 对话用引号，并注明说话者"""

        user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in (world.rules or []))}

当前情境:
{situation}

玩家行动: {action_text}

描述这个行动的结果。生动但简洁（2-3段）。"""

        narrative = await generate_narrative(system_prompt, user_prompt)
        
        # 记录事件
        event = GameEvent(
            world_id=world_id,
            timestamp=int(time.time()),
            event_type="custom_action",
            content=narrative,
            extra_data={
                "action": action_text,
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
