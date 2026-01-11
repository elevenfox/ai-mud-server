"""
NPC Manager - 动态 NPC 匹配与创建模块

功能：
1. 根据场景和剧情需求，从角色库中匹配合适的 NPC
2. 如果没有匹配的角色，自动创建新角色
3. 管理场景中的 NPC 生命周期

实现方案：LLM 驱动匹配（Phase 1）
- 使用标签预筛选候选角色
- 让 LLM 做最终决策
- 后期可升级到 Vector DB
"""

import uuid
from typing import List, Optional, Dict, Any
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from datetime import datetime

from app.models.schemas import (
    NPC, Location, World, CharacterTemplate, Player, GameEvent
)
from app.core.ai import generate_json, MOCK_MODE


class NPCManager:
    """NPC 动态管理器"""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def get_scene_npcs(
        self,
        world_id: str,
        location_id: str,
        story_context: str = "",
        player_id: Optional[str] = None
    ) -> List[NPC]:
        """
        获取场景中应该出现的 NPC
        
        逻辑：
        1. 先获取当前已在场景中的 NPC
        2. 根据场景和剧情，判断是否需要加载更多 NPC
        3. 如果需要，从角色库匹配或创建
        """
        # 获取当前场景已有的 NPC
        stmt = select(NPC).where(
            NPC.world_id == world_id,
            NPC.location_id == location_id
        )
        results = await self.session.execute(stmt)
        existing_npcs = list(results.scalars().all())
        
        # 如果场景已有 NPC 或没有故事上下文，直接返回
        if existing_npcs or not story_context:
            return existing_npcs
        
        # 获取场景信息
        location = await self.session.get(Location, location_id)
        if not location:
            return existing_npcs
        
        # 根据场景判断需要什么角色
        needed_roles = await self._analyze_scene_needs(location, story_context)
        
        if not needed_roles:
            return existing_npcs
        
        # 为每个需要的角色匹配或创建 NPC
        for role_info in needed_roles:
            npc = await self._find_or_create_npc(
                world_id=world_id,
                location_id=location_id,
                role_needed=role_info.get("role", "路人"),
                role_description=role_info.get("description", ""),
                scene_context=f"{location.name}: {location.description}",
                story_context=story_context
            )
            if npc:
                existing_npcs.append(npc)
        
        return existing_npcs
    
    async def _analyze_scene_needs(
        self,
        location: Location,
        story_context: str
    ) -> List[Dict[str, str]]:
        """分析场景需要什么类型的 NPC"""
        
        system_prompt = """你是一个游戏场景设计师。根据场景和故事上下文，判断这个场景应该有哪些 NPC。请用中文回复。

规则：
- 考虑场景类型（餐厅需要服务员、酒吧需要酒保等）
- 考虑故事需要（剧情发展可能需要特定角色）
- 不要添加太多角色（1-2 个就够）
- 如果场景不需要新角色，返回空列表

用 JSON 格式回复:
{
    "needs_npcs": true/false,
    "roles": [
        {"role": "角色类型，如：服务员", "description": "简短描述角色应该是什么样的"},
        ...
    ],
    "reasoning": "为什么需要/不需要这些角色"
}"""

        user_prompt = f"""场景：{location.name}
场景描述：{location.description}
场景标签：{location.tags if hasattr(location, 'tags') else '无'}

故事上下文：
{story_context}

这个场景需要添加什么 NPC？"""

        if MOCK_MODE:
            # Mock 模式：根据场景名称简单判断
            if "餐" in location.name or "饭" in location.name:
                return [{"role": "服务员", "description": "热情的餐厅服务员"}]
            elif "酒吧" in location.name or "bar" in location.name.lower():
                return [{"role": "酒保", "description": "沉默寡言的酒保"}]
            return []
        
        result = await generate_json(system_prompt, user_prompt)
        
        if result.get("needs_npcs") and result.get("roles"):
            return result["roles"]
        return []
    
    async def _find_or_create_npc(
        self,
        world_id: str,
        location_id: str,
        role_needed: str,
        role_description: str,
        scene_context: str,
        story_context: str
    ) -> Optional[NPC]:
        """从角色库匹配或创建新 NPC"""
        
        # Step 1: 从角色库预筛选候选
        candidates = await self._get_candidate_templates(role_needed)
        
        # Step 2: 让 LLM 选择或创建
        result = await self._llm_select_or_create(
            candidates=candidates,
            role_needed=role_needed,
            role_description=role_description,
            scene_context=scene_context,
            story_context=story_context
        )
        
        if not result:
            return None
        
        # Step 3: 根据 LLM 决策执行
        if result.get("action") == "select" and result.get("template_id"):
            # 从模板创建 NPC
            return await self._create_npc_from_template(
                world_id=world_id,
                location_id=location_id,
                template_id=result["template_id"],
                customizations=result.get("customizations", {})
            )
        elif result.get("action") == "create" and result.get("new_character"):
            # 创建全新 NPC
            return await self._create_new_npc(
                world_id=world_id,
                location_id=location_id,
                character_data=result["new_character"]
            )
        
        return None
    
    async def _get_candidate_templates(
        self,
        role_needed: str,
        limit: int = 10
    ) -> List[CharacterTemplate]:
        """从角色库获取候选模板（标签预筛选）"""
        
        # 获取所有角色模板
        stmt = select(CharacterTemplate).limit(50)
        results = await self.session.execute(stmt)
        all_templates = list(results.scalars().all())
        
        # 简单的关键词匹配（后期可升级为向量搜索）
        role_keywords = role_needed.lower().split()
        scored_templates = []
        
        for template in all_templates:
            score = 0
            # 检查标签匹配
            template_tags = [t.lower() for t in (template.tags or [])]
            for keyword in role_keywords:
                if any(keyword in tag for tag in template_tags):
                    score += 2
            
            # 检查名称/描述匹配
            template_text = f"{template.name} {template.description} {template.personality}".lower()
            for keyword in role_keywords:
                if keyword in template_text:
                    score += 1
            
            if score > 0:
                scored_templates.append((score, template))
        
        # 按分数排序，返回前 N 个
        scored_templates.sort(key=lambda x: x[0], reverse=True)
        return [t for _, t in scored_templates[:limit]]
    
    async def _llm_select_or_create(
        self,
        candidates: List[CharacterTemplate],
        role_needed: str,
        role_description: str,
        scene_context: str,
        story_context: str
    ) -> Optional[Dict[str, Any]]:
        """LLM 决定选择现有角色还是创建新角色"""
        
        system_prompt = """你是一个游戏角色选角导演。根据场景需求，从候选角色中选择最合适的，或建议创建新角色。请用中文回复。

规则：
- 如果有合适的候选角色，优先选择
- 只有在没有合适候选时才创建新角色
- 创建的新角色要符合场景氛围
- 新角色需要有完整的性格、外貌、说话方式

用 JSON 格式回复:
{
    "action": "select" 或 "create",
    "reasoning": "选择或创建的理由",
    
    // 如果 action 是 "select"：
    "template_id": "选中的角色模板 ID",
    "customizations": {
        "name": "可选：自定义名字",
        "personality_addition": "可选：额外性格特点"
    },
    
    // 如果 action 是 "create"：
    "new_character": {
        "name": "角色名",
        "description": "外貌描述（2-3句）",
        "personality": "性格特点",
        "first_message": "角色的开场白",
        "tags": ["标签1", "标签2"]
    }
}"""

        # 构建候选列表
        candidates_text = "无候选角色"
        if candidates:
            candidates_list = []
            for c in candidates:
                candidates_list.append(
                    f"- ID: {c.id}\n"
                    f"  名字: {c.name}\n"
                    f"  描述: {c.description[:100]}...\n"
                    f"  性格: {c.personality[:100]}...\n"
                    f"  标签: {', '.join(c.tags or [])}"
                )
            candidates_text = "\n".join(candidates_list)
        
        user_prompt = f"""需要的角色类型：{role_needed}
角色描述：{role_description}

场景：{scene_context}

故事上下文：{story_context}

候选角色库：
{candidates_text}

请选择最合适的角色，或创建新角色。"""

        if MOCK_MODE:
            # Mock 模式：如果有候选就选第一个，否则创建
            if candidates:
                return {
                    "action": "select",
                    "template_id": candidates[0].id,
                    "customizations": {},
                    "reasoning": "[MOCK] 选择第一个候选"
                }
            else:
                return {
                    "action": "create",
                    "new_character": {
                        "name": f"{role_needed}",
                        "description": f"一个{role_description or '普通的'}{role_needed}",
                        "personality": "友善，乐于助人",
                        "first_message": f"*{role_needed}注意到你走进来* 欢迎！有什么可以帮您的？",
                        "tags": [role_needed]
                    },
                    "reasoning": "[MOCK] 没有候选，创建新角色"
                }
        
        return await generate_json(system_prompt, user_prompt)
    
    async def _create_npc_from_template(
        self,
        world_id: str,
        location_id: str,
        template_id: str,
        customizations: Dict[str, Any] = None
    ) -> Optional[NPC]:
        """从角色模板创建 NPC 实例"""
        
        template = await self.session.get(CharacterTemplate, template_id)
        if not template:
            return None
        
        customizations = customizations or {}
        
        npc_id = f"npc_{uuid.uuid4().hex[:8]}"
        npc = NPC(
            id=npc_id,
            world_id=world_id,
            name=customizations.get("name") or template.name,
            description=template.description,
            personality=template.personality + (
                f"\n{customizations.get('personality_addition', '')}"
                if customizations.get('personality_addition') else ""
            ),
            location_id=location_id,
            portrait_url=template.portrait_path,
            first_message=template.first_message,
            scenario=template.scenario,
            example_dialogs=template.example_dialogs or [],
            current_emotion="default",
            relationship=0,
            position="center"
        )
        
        self.session.add(npc)
        await self.session.commit()
        await self.session.refresh(npc)
        
        return npc
    
    async def _create_new_npc(
        self,
        world_id: str,
        location_id: str,
        character_data: Dict[str, Any]
    ) -> Optional[NPC]:
        """创建全新的 NPC（同时保存到角色库）"""
        
        # 先创建角色模板（保存到角色库供后续使用）
        template_id = f"char_{uuid.uuid4().hex[:8]}"
        template = CharacterTemplate(
            id=template_id,
            name=character_data.get("name", "未命名"),
            description=character_data.get("description", ""),
            personality=character_data.get("personality", ""),
            first_message=character_data.get("first_message"),
            tags=character_data.get("tags", []),
            is_player_avatar=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        self.session.add(template)
        
        # 创建 NPC 实例
        npc_id = f"npc_{uuid.uuid4().hex[:8]}"
        npc = NPC(
            id=npc_id,
            world_id=world_id,
            name=character_data.get("name", "未命名"),
            description=character_data.get("description", ""),
            personality=character_data.get("personality", ""),
            location_id=location_id,
            portrait_url=None,  # 新创建的角色暂无立绘
            first_message=character_data.get("first_message"),
            scenario=None,
            example_dialogs=[],
            current_emotion="default",
            relationship=0,
            position="center"
        )
        
        self.session.add(npc)
        await self.session.commit()
        await self.session.refresh(npc)
        
        return npc
    
    async def move_npc(
        self,
        npc_id: str,
        new_location_id: str,
        reason: str = ""
    ) -> bool:
        """移动 NPC 到新场景"""
        npc = await self.session.get(NPC, npc_id)
        if not npc:
            return False
        
        npc.location_id = new_location_id
        self.session.add(npc)
        await self.session.commit()
        return True
    
    async def update_npc_state(
        self,
        npc_id: str,
        emotion: Optional[str] = None,
        relationship_change: int = 0,
        position: Optional[str] = None
    ) -> Optional[NPC]:
        """更新 NPC 状态"""
        npc = await self.session.get(NPC, npc_id)
        if not npc:
            return None
        
        if emotion:
            npc.current_emotion = emotion
        
        if relationship_change:
            npc.relationship = max(-100, min(100, npc.relationship + relationship_change))
        
        if position:
            npc.position = position
        
        self.session.add(npc)
        await self.session.commit()
        await self.session.refresh(npc)
        
        return npc
    
    async def remove_npc_from_scene(
        self,
        npc_id: str,
        world_id: str
    ) -> bool:
        """从场景移除 NPC（不删除，只是移到一个"离开"状态）"""
        npc = await self.session.get(NPC, npc_id)
        if not npc:
            return False
        
        # 可以设置一个特殊的 location_id 表示"不在任何场景"
        # 或者直接删除（取决于游戏设计）
        npc.location_id = f"offscreen_{world_id}"
        self.session.add(npc)
        await self.session.commit()
        return True


# ============== 辅助函数 ==============

async def spawn_npcs_for_scene(
    session: AsyncSession,
    world_id: str,
    location_id: str,
    story_context: str = ""
) -> List[NPC]:
    """
    便捷函数：为场景生成/加载 NPC
    
    用法：
        npcs = await spawn_npcs_for_scene(session, world_id, location_id, "玩家刚进入餐厅")
    """
    manager = NPCManager(session)
    return await manager.get_scene_npcs(
        world_id=world_id,
        location_id=location_id,
        story_context=story_context
    )
