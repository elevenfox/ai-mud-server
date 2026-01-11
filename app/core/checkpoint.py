"""Checkpoint 存档系统"""

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Dict, Any, List, Optional
from datetime import datetime
import uuid
import json

from app.models.schemas import (
    World, Location, Player, NPC, GameEvent, Conversation, Checkpoint
)


class CheckpointManager:
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_checkpoint(
        self,
        world_id: str,
        player_id: str,
        description: str = "",
        is_auto: bool = False
    ) -> Checkpoint:
        """创建存档点"""
        # 收集世界状态快照
        snapshot = await self._collect_world_snapshot(world_id, player_id)
        
        checkpoint = Checkpoint(
            id=f"cp_{uuid.uuid4().hex[:8]}",
            world_id=world_id,
            player_id=player_id,
            created_at=datetime.utcnow(),
            description=description or f"Checkpoint at {datetime.utcnow().isoformat()}",
            world_snapshot=snapshot,
            is_auto=is_auto
        )
        
        self.session.add(checkpoint)
        await self.session.commit()
        
        return checkpoint
    
    async def _collect_world_snapshot(self, world_id: str, player_id: str) -> Dict[str, Any]:
        """收集完整的世界状态快照"""
        # World
        world = await self.session.get(World, world_id)
        
        # Player
        player = await self.session.get(Player, player_id)
        
        # All locations in this world
        loc_stmt = select(Location).where(Location.world_id == world_id)
        loc_results = await self.session.execute(loc_stmt)
        locations = loc_results.scalars().all()
        
        # All NPCs in this world
        npc_stmt = select(NPC).where(NPC.world_id == world_id)
        npc_results = await self.session.execute(npc_stmt)
        npcs = npc_results.scalars().all()
        
        # Recent game events (last 50)
        event_stmt = (
            select(GameEvent)
            .where(GameEvent.world_id == world_id)
            .order_by(GameEvent.timestamp.desc())
            .limit(50)
        )
        event_results = await self.session.execute(event_stmt)
        events = event_results.scalars().all()
        
        # Conversations with this player (last 100)
        conv_stmt = (
            select(Conversation)
            .where(Conversation.world_id == world_id)
            .where(Conversation.player_id == player_id)
            .order_by(Conversation.timestamp.desc())
            .limit(100)
        )
        conv_results = await self.session.execute(conv_stmt)
        conversations = conv_results.scalars().all()
        
        return {
            "world": {
                "id": world.id,
                "time": world.time,
                "seed": world.seed,
                "name": world.name,
                "description": world.description,
                "rules": world.rules,
                "flags": world.flags,
                "current_mood": world.current_mood
            },
            "player": {
                "id": player.id,
                "name": player.name,
                "location_id": player.location_id,
                "inventory": player.inventory
            },
            "locations": [
                {
                    "id": loc.id,
                    "name": loc.name,
                    "description": loc.description,
                    "background_url": loc.background_url,
                    "connections": loc.connections
                }
                for loc in locations
            ],
            "npcs": [
                {
                    "id": npc.id,
                    "name": npc.name,
                    "description": npc.description,
                    "personality": npc.personality,
                    "location_id": npc.location_id,
                    "portrait_url": npc.portrait_url,
                    "first_message": npc.first_message,
                    "scenario": npc.scenario,
                    "example_dialogs": npc.example_dialogs,
                    "current_emotion": npc.current_emotion,
                    "relationship": npc.relationship
                }
                for npc in npcs
            ],
            "events": [
                {
                    "id": e.id,
                    "timestamp": e.timestamp,
                    "event_type": e.event_type,
                    "content": e.content,
                    "extra_data": e.extra_data
                }
                for e in events
            ],
            "conversations": [
                {
                    "id": c.id,
                    "npc_id": c.npc_id,
                    "timestamp": c.timestamp,
                    "role": c.role,
                    "content": c.content
                }
                for c in conversations
            ]
        }
    
    async def load_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """从存档点恢复世界状态"""
        checkpoint = await self.session.get(Checkpoint, checkpoint_id)
        if not checkpoint:
            return {"error": "Checkpoint not found"}
        
        snapshot = checkpoint.world_snapshot
        world_id = snapshot["world"]["id"]
        player_id = snapshot["player"]["id"]
        
        # 恢复 World
        world = await self.session.get(World, world_id)
        if world:
            world.time = snapshot["world"]["time"]
            world.flags = snapshot["world"]["flags"]
            world.current_mood = snapshot["world"]["current_mood"]
            self.session.add(world)
        
        # 恢复 Player
        player = await self.session.get(Player, player_id)
        if player:
            player.location_id = snapshot["player"]["location_id"]
            player.inventory = snapshot["player"]["inventory"]
            self.session.add(player)
        
        # 恢复 NPCs
        for npc_data in snapshot["npcs"]:
            npc = await self.session.get(NPC, npc_data["id"])
            if npc:
                npc.location_id = npc_data["location_id"]
                npc.current_emotion = npc_data["current_emotion"]
                npc.relationship = npc_data["relationship"]
                self.session.add(npc)
        
        await self.session.commit()
        
        return {
            "success": True,
            "checkpoint_id": checkpoint_id,
            "description": checkpoint.description,
            "restored_at": datetime.utcnow().isoformat()
        }
    
    async def list_checkpoints(
        self, 
        world_id: str, 
        player_id: str,
        include_auto: bool = True
    ) -> List[Dict[str, Any]]:
        """列出所有存档点"""
        stmt = (
            select(Checkpoint)
            .where(Checkpoint.world_id == world_id)
            .where(Checkpoint.player_id == player_id)
        )
        
        if not include_auto:
            stmt = stmt.where(Checkpoint.is_auto == False)
        
        stmt = stmt.order_by(Checkpoint.created_at.desc())
        
        results = await self.session.execute(stmt)
        checkpoints = results.scalars().all()
        
        return [
            {
                "id": cp.id,
                "description": cp.description,
                "created_at": cp.created_at.isoformat(),
                "is_auto": cp.is_auto
            }
            for cp in checkpoints
        ]
    
    async def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """删除存档点"""
        checkpoint = await self.session.get(Checkpoint, checkpoint_id)
        if checkpoint:
            await self.session.delete(checkpoint)
            await self.session.commit()
            return True
        return False
