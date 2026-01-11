"""NPC 对话代理 - 每个 NPC 有独立人格"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import List, Dict, Optional
import time

from app.models.schemas import NPC, Player, World, Location, Conversation, GameEvent
from app.core.ai import generate_npc_response


class NPCAgent:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_conversation_history(
        self, 
        world_id: str, 
        npc_id: str, 
        player_id: str,
        limit: int = 20
    ) -> List[Dict[str, str]]:
        """获取与特定 NPC 的对话历史"""
        statement = (
            select(Conversation)
            .where(Conversation.world_id == world_id)
            .where(Conversation.npc_id == npc_id)
            .where(Conversation.player_id == player_id)
            .order_by(Conversation.timestamp.desc())
            .limit(limit)
        )
        results = await self.session.execute(statement)
        conversations = results.scalars().all()
        
        # 按时间正序返回
        return [
            {"role": conv.role, "content": conv.content}
            for conv in reversed(conversations)
        ]
    
    async def build_world_context(self, world: World, location: Location, npcs_here: List[NPC]) -> str:
        """构建世界上下文供 NPC 参考"""
        other_npcs = [n.name for n in npcs_here if n.id != "current"]
        
        context = f"""Current time: {world.time}
Location: {location.name} - {location.description}
Other characters present: {', '.join(other_npcs) if other_npcs else 'None'}
World state flags: {world.flags}
Current atmosphere: {world.current_mood}"""
        return context
    
    async def talk_to_npc(
        self,
        world_id: str,
        player_id: str,
        npc_id: str,
        player_message: str
    ) -> Dict:
        """与 NPC 对话"""
        # 获取所需数据
        world = await self.session.get(World, world_id)
        player = await self.session.get(Player, player_id)
        npc = await self.session.get(NPC, npc_id)
        location = await self.session.get(Location, player.location_id)
        
        if not npc:
            return {"error": "NPC not found"}
        
        # 检查 NPC 是否在同一地点
        if npc.location_id != player.location_id:
            return {"error": f"{npc.name} is not here."}
        
        # 获取同地点的其他 NPC
        statement = select(NPC).where(NPC.location_id == location.id)
        results = await self.session.execute(statement)
        npcs_here = results.scalars().all()
        
        # 获取对话历史
        history = await self.get_conversation_history(world_id, npc_id, player_id)
        
        # 构建世界上下文
        world_context = await self.build_world_context(world, location, npcs_here)
        
        # 生成 NPC 回复
        response = await generate_npc_response(
            npc_name=npc.name,
            npc_personality=npc.personality,
            npc_description=npc.description,
            scenario=npc.scenario,
            example_dialogs=npc.example_dialogs or [],
            conversation_history=history,
            player_message=player_message,
            world_context=world_context
        )
        
        # 保存对话记录
        now = int(time.time())
        
        player_conv = Conversation(
            world_id=world_id,
            npc_id=npc_id,
            player_id=player_id,
            timestamp=now,
            role="player",
            content=player_message
        )
        self.session.add(player_conv)
        
        npc_conv = Conversation(
            world_id=world_id,
            npc_id=npc_id,
            player_id=player_id,
            timestamp=now + 1,
            role="npc",
            content=response.get("response", "...")
        )
        self.session.add(npc_conv)
        
        # 更新 NPC 情绪
        new_emotion = response.get("emotion", "default")
        relationship_change = response.get("relationship_change", 0)
        
        npc.current_emotion = new_emotion
        npc.relationship = max(-100, min(100, npc.relationship + relationship_change))
        self.session.add(npc)
        
        # 记录游戏事件
        event = GameEvent(
            world_id=world_id,
            timestamp=now,
            event_type="talk",
            content=response.get("response", "..."),
            extra_data={
                "npc_id": npc_id,
                "npc_name": npc.name,
                "player_message": player_message,
                "emotion": new_emotion,
                "mood": world.current_mood
            }
        )
        self.session.add(event)
        
        await self.session.commit()
        
        return {
            "npc_name": npc.name,
            "response": response.get("response", "..."),
            "emotion": new_emotion,
            "relationship": npc.relationship,
            "portrait_url": self._get_portrait_url(npc, new_emotion),
            "mood": world.current_mood
        }
    
    def _get_portrait_url(self, npc: NPC, emotion: str) -> Optional[str]:
        """根据情绪获取对应的立绘 URL"""
        if not npc.portrait_url:
            return None
        
        # 假设立绘文件名格式: /static/npcs/{npc_id}/{emotion}.png
        # 如果没有特定情绪的立绘，返回默认
        base_url = npc.portrait_url.rsplit('/', 1)[0] if '/' in npc.portrait_url else ""
        return f"{base_url}/{emotion}.png" if base_url else npc.portrait_url
    
    async def get_first_meeting_message(self, npc_id: str, world_id: str, player_id: str) -> Optional[str]:
        """获取 NPC 首次见面的开场白"""
        npc = await self.session.get(NPC, npc_id)
        if not npc:
            return None
        
        # 检查是否有对话历史
        history = await self.get_conversation_history(world_id, npc_id, player_id, limit=1)
        
        if not history and npc.first_message:
            return npc.first_message
        
        return None
