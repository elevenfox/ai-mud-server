"""图片生成模块 - 使用 OpenAI DALL-E 生成场景背景和角色立绘"""

import os
import uuid
from pathlib import Path
from typing import Optional
from openai import AsyncOpenAI
from dotenv import load_dotenv
import aiohttp
import aiofiles

load_dotenv()

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"
# 支持本地 LLM：如果 LOCAL_LLM 不为空，使用本地 API；否则使用 OpenAI
LOCAL_LLM = os.getenv("LOCAL_LLM", "").strip()
if not MOCK_MODE:
    if LOCAL_LLM:
        # 使用本地 LLM API（假设格式兼容 OpenAI）
        # 确保 URL 格式正确（添加 /v1 如果不存在）
        base_url = LOCAL_LLM.rstrip('/')
        if not base_url.endswith('/v1'):
            base_url = f"{base_url}/v1"
        
        print(f"🔧 图片生成使用本地 LLM API: {base_url}")
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "not-needed"),  # 本地 LLM 可能不需要 key
            base_url=base_url,
            timeout=120.0  # 图片生成可能需要更长时间
        )
    else:
        # 使用 OpenAI API
        print("🔧 图片生成使用 OpenAI API")
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    client = None
    print("🔧 图片生成使用 MOCK 模式")


async def generate_image(
    prompt: str,
    size: str = "1024x1024",
    quality: str = "standard",
    style: Optional[str] = None
) -> Optional[bytes]:
    """使用 DALL-E 生成图片
    
    Args:
        prompt: 图片描述提示词
        size: 图片尺寸 (1024x1024, 1792x1024, 1024x1792)
        quality: 图片质量 (standard, hd)
        style: 风格 (vivid, natural)
    
    Returns:
        图片的二进制数据，如果失败返回 None
    """
    if MOCK_MODE:
        print(f"[MOCK] 生成图片: {prompt[:50]}...")
        return None
    
    if not client:
        print("⚠️  OpenAI API key 未设置，跳过图片生成")
        return None
    
    try:
        response = await client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size=size,
            quality=quality,
            style=style or "vivid",
            n=1
        )
        
        image_url = response.data[0].url
        
        # 下载图片
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status == 200:
                    return await resp.read()
        
        return None
    except Exception as e:
        print(f"❌ 图片生成失败: {e}")
        return None


async def generate_scene_background(
    location_name: str,
    description: str,
    style: str = "cyberpunk, digital art, detailed, atmospheric"
) -> Optional[bytes]:
    """生成场景背景图片
    
    Args:
        location_name: 场景名称
        description: 场景描述
        style: 艺术风格
    
    Returns:
        图片二进制数据
    """
    prompt = f"{description}, {style}, wide angle view, background image, no characters, cinematic lighting"
    return await generate_image(prompt, size="1792x1024", quality="hd", style="vivid")


async def generate_character_portrait(
    character_name: str,
    description: str,
    personality: str = "",
    style: str = "anime, cartoon, character portrait, detailed, colorful"
) -> Optional[bytes]:
    """生成角色立绘
    
    Args:
        character_name: 角色名称
        description: 角色描述
        personality: 性格描述
        style: 艺术风格
    
    Returns:
        图片二进制数据
    """
    personality_hint = f", {personality}" if personality else ""
    prompt = f"{description}{personality_hint}, {style}, character portrait, full body or upper body, facing camera, detailed facial features, expressive"
    return await generate_image(prompt, size="1024x1024", quality="hd", style="vivid")


async def save_image(
    image_data: bytes,
    save_path: Path,
    format: str = "png"
) -> bool:
    """保存图片到文件
    
    Args:
        image_data: 图片二进制数据
        save_path: 保存路径
        format: 图片格式 (png, jpg)
    
    Returns:
        是否成功
    """
    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(save_path, 'wb') as f:
            await f.write(image_data)
        return True
    except Exception as e:
        print(f"❌ 保存图片失败: {e}")
        return False
