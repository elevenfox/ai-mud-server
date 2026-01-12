"""角色立绘管理器 - 根据 prompt 生成 tag 并动态生成立绘"""

import os
from pathlib import Path
from typing import Optional, Dict, Any
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from app.models.schemas import CharacterTemplate, NPC, Player
from app.core.ai import generate_json
from app.core.image_generator import generate_image, save_image
from app.services.chub_parser import extract_chara_from_png
import aiofiles
import base64
import aiohttp
from urllib.parse import quote


async def analyze_portrait_tag(
    prompt: str,
    character_name: str,
    character_description: str = "",
    character_personality: str = ""
) -> str:
    """根据 prompt 分析出立绘 tag
    
    Args:
        prompt: 描述情绪/状态的 prompt（如："玩家很开心"、"NPC 很愤怒"）
        character_name: 角色名称
        character_description: 角色描述
        character_personality: 角色性格
    
    Returns:
        tag 字符串（如："happy", "angry", "fearful", "surprised", "sad", "default"）
    """
    system_prompt = """你是一个游戏立绘标签分析器。根据玩家的互动描述，分析出角色当前的情绪或状态标签。

可用的标签：
- happy: 开心、高兴、愉悦、兴奋
- angry: 愤怒、生气、恼火
- sad: 悲伤、沮丧、失落
- surprised: 惊讶、震惊、意外
- fearful: 恐惧、害怕、惊恐、紧张
- default: 默认、平静、中性

用 JSON 格式回复:
{
    "tag": "happy|angry|sad|surprised|fearful|default"
}"""

    user_prompt = f"""角色信息：
名称: {character_name}
描述: {character_description}
性格: {character_personality}

当前情况: {prompt}

请分析这个角色当前的情绪或状态，返回对应的标签。"""

    try:
        result = await generate_json(system_prompt, user_prompt)
        tag = result.get("tag", "default")
        
        # 验证 tag 是否有效
        valid_tags = ["happy", "angry", "sad", "surprised", "fearful", "default"]
        if tag not in valid_tags:
            tag = "default"
        
        return tag
    except Exception as e:
        print(f"⚠️  分析 tag 失败: {e}")
        return "default"


async def get_or_generate_portrait(
    session: AsyncSession,
    character_template_id: str,
    tag: str,
    prompt: str = "",
    base_portrait_path: Optional[str] = None
) -> Optional[str]:
    """获取或生成指定 tag 的立绘
    
    Args:
        session: 数据库会话
        character_template_id: 角色模板 ID
        tag: 立绘标签（如 "happy", "angry"）
        prompt: 描述当前情况的 prompt（用于生成新立绘）
        base_portrait_path: 基础立绘路径（如果为 None，会从模板中获取）
    
    Returns:
        立绘 URL 路径，如果失败返回 None
    """
    # ====== 临时功能：从外部 API 获取立绘 ======
    try:
        # 获取角色模板以获取角色姓名
        template = await session.get(CharacterTemplate, character_template_id)
        if template and template.name:
            character_name = template.name
            # 调用外部 API（URL 编码角色姓名以支持中文）
            encoded_name = quote(character_name)
            api_url = f"http://dev.tuzac.com/api/?ac=get_random_photo_by_search&keywords={encoded_name}"
            async with aiohttp.ClientSession() as http_session:
                async with http_session.get(api_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == 1 and data.get("src"):
                            src = data["src"]
                            # 确保 URL 完整
                            if src.startswith("http"):
                                return src
                            else:
                                return f"http://dev.tuzac.com{src}"
        print(f"⚠️  外部 API 获取立绘失败，继续使用原有逻辑")
    except Exception as e:
        print(f"⚠️  外部 API 调用异常: {e}，继续使用原有逻辑")
    # ====== 临时功能结束 ======
    
    # 获取角色模板
    template = await session.get(CharacterTemplate, character_template_id)
    if not template:
        print(f"⚠️  角色模板不存在: {character_template_id}")
        return None
    
    # 获取或初始化 portrait_variants
    portrait_variants = template.portrait_variants or {}
    
    # 如果该 tag 的立绘已存在，直接返回
    if tag in portrait_variants and portrait_variants[tag]:
        portrait_path = portrait_variants[tag]
        # 验证文件是否存在
        full_path = Path(__file__).parent.parent.parent / portrait_path.lstrip('/')
        if full_path.exists():
            return portrait_path
    
    # 如果不存在，需要生成新立绘
    print(f"🎨 为角色「{template.name}」生成 {tag} 标签的立绘...")
    
    # 获取基础立绘路径
    if not base_portrait_path:
        base_portrait_path = template.portrait_path
    
    # 构建生成立绘的 prompt
    emotion_descriptions = {
        "happy": "开心、高兴、面带笑容、眼神明亮",
        "angry": "愤怒、生气、眉头紧皱、眼神锐利",
        "sad": "悲伤、沮丧、眼神黯淡、表情低落",
        "surprised": "惊讶、震惊、眼睛睁大、嘴巴微张",
        "fearful": "恐惧、害怕、眼神惊恐、表情紧张",
        "default": "平静、中性、自然表情"
    }
    
    emotion_desc = emotion_descriptions.get(tag, "自然表情")
    
    # 如果有基础立绘，可以基于它生成（使用 DALL-E 的 image variation 或 inpainting）
    # 但 DALL-E 3 不支持 image variation，所以我们用文本描述生成
    generation_prompt = f"""{template.description}, {template.personality}, 
{emotion_desc}, 
anime style, character portrait, full body or upper body, facing camera, 
detailed facial features, expressive, consistent character design"""
    
    # 如果有 prompt，加入更多上下文
    if prompt:
        generation_prompt += f", {prompt}"
    
    # 生成立绘
    portrait_image = await generate_image(
        generation_prompt,
        size="1024x1024",
        quality="hd",
        style="vivid"
    )
    
    if not portrait_image:
        print(f"⚠️  立绘生成失败，使用默认立绘")
        # 如果生成失败，使用基础立绘或返回 None
        return base_portrait_path
    
    # 保存立绘
    char_dir = Path("static/uploads/characters") / character_template_id
    char_dir.mkdir(parents=True, exist_ok=True)
    portrait_file = char_dir / f"portrait_{tag}.png"
    
    if await save_image(portrait_image, portrait_file, "png"):
        portrait_path = f"/static/uploads/characters/{character_template_id}/portrait_{tag}.png"
        
        # 更新数据库
        if not portrait_variants:
            portrait_variants = {}
        portrait_variants[tag] = portrait_path
        template.portrait_variants = portrait_variants
        session.add(template)
        await session.commit()
        
        print(f"✅ 立绘已保存: {portrait_path}")
        return portrait_path
    else:
        print(f"⚠️  立绘保存失败")
        return base_portrait_path


async def update_character_portrait_by_prompt(
    session: AsyncSession,
    character_template_id: str,
    prompt: str,
    character_description: str = "",
    character_personality: str = ""
) -> Optional[str]:
    """根据 prompt 更新角色立绘（完整流程）
    
    1. 分析 prompt 得到 tag
    2. 获取或生成对应 tag 的立绘
    3. 返回立绘 URL
    
    Args:
        session: 数据库会话
        character_template_id: 角色模板 ID
        prompt: 描述当前情况的 prompt（如："玩家很开心"、"NPC 很愤怒"）
        character_description: 角色描述（如果为空，会从模板中获取）
        character_personality: 角色性格（如果为空，会从模板中获取）
    
    Returns:
        立绘 URL 路径，如果失败返回 None
    """
    # 获取角色模板
    template = await session.get(CharacterTemplate, character_template_id)
    if not template:
        return None
    
    # 如果没有提供描述和性格，从模板中获取
    if not character_description:
        character_description = template.description or ""
    if not character_personality:
        character_personality = template.personality or ""
    
    # 1. 分析 tag
    tag = await analyze_portrait_tag(
        prompt,
        template.name,
        character_description,
        character_personality
    )
    
    # 2. 获取或生成立绘
    portrait_url = await get_or_generate_portrait(
        session,
        character_template_id,
        tag,
        prompt,
        template.portrait_path
    )
    
    return portrait_url


async def get_npc_portrait_url(
    session: AsyncSession,
    npc: NPC,
    prompt: Optional[str] = None
) -> Optional[str]:
    """获取 NPC 的立绘 URL（支持动态 tag）
    
    Args:
        session: 数据库会话
        npc: NPC 对象
        prompt: 可选的 prompt，用于生成动态立绘
    
    Returns:
        立绘 URL
    """
    if not npc.template_id:
        return npc.portrait_url
    
    # 如果有 prompt，尝试生成动态立绘
    if prompt:
        try:
            dynamic_portrait = await update_character_portrait_by_prompt(
                session,
                npc.template_id,
                prompt
            )
            if dynamic_portrait:
                return dynamic_portrait
        except Exception as e:
            print(f"⚠️  生成动态立绘失败: {e}")
    
    # 否则使用模板的基础立绘
    template = await session.get(CharacterTemplate, npc.template_id)
    if template:
        return template.portrait_path
    
    return npc.portrait_url
