"""Judge 模块 - 校验玩家自由输入是否符合世界规则"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Dict, Any
import time

from app.models.schemas import World, Location, Player, NPC, GameEvent, JudgeResult, ActionResult, CharacterTemplate
from app.core.ai import judge_action, generate_narrative


class ActionJudge:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def _get_npc_display_name(self, npc: NPC) -> str:
        """获取 NPC 的显示名称，优先从 CharacterTemplate 获取"""
        if npc.template_id:
            template = await self.session.get(CharacterTemplate, npc.template_id)
            if template:
                # 如果 NPC 有自定义名称，优先使用；否则使用模板名称
                return npc.name if npc.name else template.name
        # 没有模板，使用 NPC 自身名称
        return npc.name or "未知"
    
    async def _get_npc_display_info(self, npc: NPC) -> Dict[str, str]:
        """获取 NPC 的完整显示信息（名称和描述），优先从 CharacterTemplate 获取"""
        if npc.template_id:
            template = await self.session.get(CharacterTemplate, npc.template_id)
            if template:
                return {
                    "name": npc.name if npc.name else template.name,
                    "description": template.description or ""
                }
        return {
            "name": npc.name or "未知",
            "description": npc.description or ""
        }
    
    async def get_physical_constraints(self, location: Location, player: Player, npcs: List[NPC]) -> List[str]:
        """获取当前环境的物理约束"""
        constraints = [
            f"玩家在 {location.name}",
            f"玩家物品: {', '.join(player.inventory) or '空'}",
        ]
        
        # 获取可访问场景的详细信息
        from sqlmodel import select
        statement = select(Location).where(Location.world_id == player.world_id)
        results = await self.session.execute(statement)
        all_locations = list(results.scalars().all())
        
        connected_names = []
        for loc in all_locations:
            if loc.id in location.connections:
                connected_names.append(loc.name)
        
        if connected_names:
            constraints.append(f"可前往的场景: {', '.join(connected_names)}")
            constraints.append("玩家可以通过说「去 [场景名]」或「前往 [场景名]」来切换场景")
        else:
            constraints.append("当前场景没有可前往的其他场景")
        
        if npcs:
            # 获取 NPC 显示名称（从模板获取）
            npc_names = []
            for npc in npcs:
                name = await self._get_npc_display_name(npc)
                npc_names.append(name)
            constraints.append(f"场景中的 NPC: {', '.join(npc_names)}")
        else:
            constraints.append("场景中没有 NPC")
        
        return constraints
    
    async def build_situation_context(
        self,
        world: World,
        location: Location,
        player: Player,
        npcs: List[NPC]
    ) -> str:
        """构建当前情境描述"""
        # 获取 NPC 信息（从模板获取）
        npc_list = []
        for npc in npcs:
            npc_info = await self._get_npc_display_info(npc)
            npc_list.append(f"- {npc_info['name']}: {npc_info['description']} (Feeling: {npc.current_emotion})")
        
        npcs_text = chr(10).join(npc_list) if npc_list else 'None'
        
        return f"""LOCATION: {location.name}
{location.description}

ATMOSPHERE: {world.current_mood}

PLAYER: {player.name}
Inventory: {', '.join(player.inventory) or 'Empty'}

NPCS HERE:
{npcs_text}

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
        
        # 检测场景切换意图
        movement_keywords = ['去', '前往', '进入', '传送到', '走到', '移动到', 'go to', 'move to', 'enter', 'teleport to']
        action_lower = action_text.lower()
        
        # 检查是否包含移动关键词
        is_movement = any(keyword in action_lower for keyword in movement_keywords)
        
        # 如果检测到移动意图，尝试解析目标场景
        if is_movement:
            # 获取所有场景
            statement = select(Location).where(Location.world_id == world_id)
            results = await self.session.execute(statement)
            all_locations = list(results.scalars().all())
            
            # 尝试匹配目标场景名称
            target_location = None
            for loc in all_locations:
                # 检查场景名称是否在输入中（支持部分匹配）
                loc_name_lower = loc.name.lower()
                # 检查完整名称或部分匹配
                if (loc.name in action_text or 
                    loc_name_lower in action_lower or
                    any(word in action_text for word in loc.name.split()) if len(loc.name) > 2 else False):
                    # 检查是否在连接列表中（允许传送到任意场景，暂时不限制）
                    # 如果场景在连接列表中，或者允许传送到任意场景
                    if loc.id in location.connections:
                        target_location = loc
                        break
                    # 如果不在连接列表中，但用户明确指定了场景名，也允许（传送到任意场景）
                    elif loc.name in action_text:
                        target_location = loc
                        break
            
            # 如果找到目标场景且不是当前场景，执行切换
            if target_location and target_location.id != location.id:
                # 保存原场景信息
                from_location = location
                to_location = target_location
                
                # 更新玩家位置
                player.location_id = to_location.id
                self.session.add(player)
                await self.session.commit()
                
                # 生成场景切换叙事
                from app.core.ai import generate_json
                
                system_prompt = """你是一个 MUD 游戏的叙事者。请用中文回复。
玩家从一个场景移动到另一个场景，请描述移动过程和到达新场景的感受。
要生动但简洁，包含感官细节。

用 JSON 格式回复:
{
    "narrative": "叙事文本（描述移动过程和到达新场景）",
    "currency_change": 0,
    "gems_change": 0
}"""
                
                # 获取新场景的 NPC
                statement = select(NPC).where(NPC.location_id == to_location.id)
                results = await self.session.execute(statement)
                npcs = list(results.scalars().all())
                
                npc_info = ""
                if npcs:
                    # 获取 NPC 显示名称（从模板获取）
                    npc_names = []
                    for npc in npcs:
                        name = await self._get_npc_display_name(npc)
                        npc_names.append(name)
                    npc_info = f"\n场景中的 NPC: {', '.join(npc_names)}"
                
                user_prompt = f"""玩家从「{from_location.name}」移动到「{to_location.name}」。

原场景: {from_location.name} - {from_location.description}
新场景: {to_location.name} - {to_location.description}
{npc_info}

请描述玩家如何从原场景移动到新场景，以及到达新场景后的第一印象。"""
                
                result = await generate_json(system_prompt, user_prompt)
                narrative = result.get("narrative", f"你来到了{to_location.name}。")
                
                # 记录事件
                event = GameEvent(
                    world_id=world_id,
                    timestamp=int(time.time()),
                    event_type="move",
                    content=narrative,
                    extra_data={
                        "from": from_location.id,
                        "to": to_location.id,
                        "action": action_text
                    }
                )
                self.session.add(event)
                await self.session.commit()
                
                return ActionResult(
                    success=True,
                    narrative=narrative,
                    mood=world.current_mood,
                    location_changed=True,
                    new_location=to_location.id,
                    currency_change=result.get("currency_change", 0),
                    gems_change=result.get("gems_change", 0)
                )
        
        # 获取当前地点的 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs = list(results.scalars().all())
        
        # 获取可访问的场景列表
        statement = select(Location).where(Location.world_id == world_id)
        results = await self.session.execute(statement)
        all_locations = list(results.scalars().all())
        
        # 构建可访问场景信息（包含场景名称和描述）
        accessible_locations = []
        for loc in all_locations:
            if loc.id in location.connections:
                accessible_locations.append(f"{loc.name}: {loc.description[:50]}...")
        
        location_info = ""
        if accessible_locations:
            location_info = f"\n\n可访问的场景:\n{chr(10).join(f'- {loc}' for loc in accessible_locations)}\n\n提示：玩家可以通过说「去 [场景名]」或「前往 [场景名]」来切换场景。"
        else:
            location_info = "\n\n当前场景没有直接连接的其他场景。"
        
        # 生成行动结果叙事（包含货币变化）
        situation = await self.build_situation_context(world, location, player, npcs)
        situation += location_info
        
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
