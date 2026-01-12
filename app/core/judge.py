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
        
        # 生成行动结果叙事（包含货币变化）
        situation = await self.build_situation_context(world, location, player, npcs)
        
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

经济系统：
- 如果玩家完成了任务、打工、寻宝等，给予适当的货币奖励
- 如果玩家消费了（购买、支付等），扣除相应的货币
- 基本价值单位：1 货币 = 1 顿普通饭的价值

用 JSON 格式回复:
{
    "narrative": "叙事文本",
    "currency_change": 0,  // 货币变化（正数=获得，负数=消费）
    "gems_change": 0,      // 宝石变化（通常为 0，除非特殊奖励）
    "reason": "货币变化的原因（可选）"
}"""

        user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in (world.rules or []))}

当前情境:
{situation}
{economy_info}

玩家行动: {action_text}

描述这个行动的结果，并判断是否需要给予货币奖励或扣除货币。生动但简洁（2-3段）。"""

        # 使用 generate_json 获取结构化结果
        from app.core.ai import generate_json
        result = await generate_json(system_prompt, user_prompt)
        narrative = result.get("narrative", "你执行了这个行动...")
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
            event_type="custom_action",
            content=narrative,
            extra_data={
                "action": action_text,
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
