from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.models.schemas import World, Location, Player, GameEvent, NPC
from app.core.ai import generate_narrative
import time

class WorldEngine:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_world_context(self, world_id: str, player_id: str):
        """获取当前玩家所在环境的完整上下文"""
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        location = await self.session.get(Location, player.location_id)
        
        # 获取当前地点的 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs = results.scalars().all()
        
        return world, player, location, npcs

    async def process_action(self, world_id: str, player_id: str, action_text: str):
        """核心循环：解析 -> 校验 -> 执行 -> 叙事"""
        world, player, location, npcs = await self.get_world_context(world_id, player_id)
        
        # 1. 简单的意图解析（Phase 1 暂时使用简单逻辑，后续可升级为 AI 解析）
        action_text = action_text.lower()
        
        if "go to" in action_text or "move to" in action_text:
            target_name = action_text.replace("go to", "").replace("move to", "").strip()
            return await self._handle_move(world, player, location, target_name)
        
        # 默认作为“观察”或“对话”处理
        return await self._handle_observation(world, player, location, npcs, action_text)

    async def _handle_move(self, world, player, current_location, target_name):
        # 校验：查找目标地点是否在连接列表中
        statement = select(Location).where(Location.world_id == world.id)
        results = await self.session.execute(statement)
        all_locations = results.scalars().all()
        
        target_location = None
        for loc in all_locations:
            if loc.name.lower() == target_name.lower() and loc.id in current_location.connections:
                target_location = loc
                break
        
        if not target_location:
            return {"status": "error", "message": f"You cannot go to '{target_name}' from here."}
        
        # 状态变更
        player.location_id = target_location.id
        self.session.add(player)
        await self.session.commit()
        
        # 叙事生成
        system_prompt = "You are a master storyteller for a MUD game. Describe the player's arrival at a new location."
        user_prompt = f"Player moved from {current_location.name} to {target_location.name}. New location description: {target_location.description}"
        narrative = await generate_narrative(system_prompt, user_prompt)
        
        # 记录事件
        event = GameEvent(
            world_id=world.id,
            timestamp=int(time.time()),
            event_type="move",
            content=narrative,
            extra_data={"from": current_location.id, "to": target_location.id}
        )
        self.session.add(event)
        await self.session.commit()
        
        return {"status": "success", "narrative": narrative, "location": target_location.name}

    async def _handle_observation(self, world, player, location, npcs, action_text):
        """处理观察或未定义的互动"""
        npc_names = [npc.name for npc in npcs]
        system_prompt = "You are a master storyteller. Describe the current scene and any NPCs present."
        user_prompt = f"Location: {location.name}. Description: {location.description}. NPCs here: {', '.join(npc_names)}. Player intent: {action_text}"
        
        narrative = await generate_narrative(system_prompt, user_prompt)
        
        event = GameEvent(
            world_id=world.id,
            timestamp=int(time.time()),
            event_type="observation",
            content=narrative,
            extra_data={"location_id": location.id}
        )
        self.session.add(event)
        await self.session.commit()
        
        return {"status": "success", "narrative": narrative}
