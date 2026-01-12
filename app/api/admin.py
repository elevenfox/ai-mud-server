"""Admin API - 管理界面后端接口"""

import os
import uuid
import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from dotenv import load_dotenv

from app.db.session import get_session
from app.models.schemas import (
    CharacterTemplate, LocationTemplate, World,
    AdminLoginRequest, AdminLoginResponse,
    CharacterTemplateCreate, CharacterTemplateUpdate,
    LocationTemplateCreate, LocationTemplateUpdate,
    WorldRulesUpdate, EconomyConfigUpdate
)
from app.services.chub_parser import (
    embed_location_to_png, extract_chara_from_png, embed_chara_to_png,
    parse_character_card, create_character_card,
    parse_location_card, create_location_card
)
from app.core.image_generator import (
    generate_scene_background,
    generate_character_portrait,
    save_image
)

load_dotenv()

router = APIRouter(prefix="/admin", tags=["admin"])

# 简单的 token 存储（生产环境应使用 Redis 或数据库）
_active_tokens = set()

ADMIN_PASSWORD = os.getenv("ADMIN_PWD", "admin123")
UPLOAD_DIR = Path(__file__).parent.parent.parent / "static" / "uploads"


def verify_admin_token(authorization: str = Header(None)) -> bool:
    """验证 Admin Token"""
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")
    
    token = authorization.replace("Bearer ", "")
    if token not in _active_tokens:
        raise HTTPException(status_code=401, detail="无效的认证信息")
    
    return True


# ============== 认证 ==============

@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(request: AdminLoginRequest):
    """Admin 登录"""
    if request.password != ADMIN_PASSWORD:
        return AdminLoginResponse(success=False, message="密码错误")
    
    # 生成 token
    token = secrets.token_urlsafe(32)
    _active_tokens.add(token)
    
    return AdminLoginResponse(success=True, token=token)


@router.post("/logout")
async def admin_logout(authorization: str = Header(None)):
    """Admin 登出"""
    if authorization:
        token = authorization.replace("Bearer ", "")
        _active_tokens.discard(token)
    return {"success": True}


# ============== 角色模板管理 ==============

@router.get("/characters")
async def list_characters(
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取所有角色模板"""
    statement = select(CharacterTemplate).order_by(CharacterTemplate.created_at.desc())
    results = await session.execute(statement)
    characters = results.scalars().all()
    
    return {
        "characters": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "personality": c.personality,
                "portrait_path": c.portrait_path,
                "tags": c.tags,
                "is_player_avatar": c.is_player_avatar,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in characters
        ]
    }


@router.post("/characters")
async def create_character(
    data: CharacterTemplateCreate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """手动创建角色模板"""
    character = CharacterTemplate(
        id=f"char_{uuid.uuid4().hex[:8]}",
        name=data.name,
        description=data.description,
        personality=data.personality,
        first_message=data.first_message,
        scenario=data.scenario,
        example_dialogs=data.example_dialogs,
        tags=data.tags,
        is_player_avatar=data.is_player_avatar,
        initial_attributes=data.initial_attributes,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    session.add(character)
    await session.commit()
    
    return {"success": True, "id": character.id}


@router.post("/characters/import")
async def import_character_png(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """从 Chub.ai PNG 导入角色"""
    if not file.filename.lower().endswith('.png'):
        raise HTTPException(status_code=400, detail="只支持 PNG 文件")
    
    # 读取文件
    content = await file.read()
    
    # 提取元数据
    chara_data = extract_chara_from_png(content)
    if not chara_data:
        raise HTTPException(status_code=400, detail="PNG 文件中没有找到角色卡数据")
    
    # 解析角色卡
    parsed = parse_character_card(chara_data)
    
    # 保存图片
    char_id = f"char_{uuid.uuid4().hex[:8]}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    portrait_dir = UPLOAD_DIR / "characters" / char_id
    portrait_dir.mkdir(parents=True, exist_ok=True)
    portrait_path = portrait_dir / "portrait.png"
    portrait_path.write_bytes(content)
    
    # 创建数据库记录
    character = CharacterTemplate(
        id=char_id,
        name=parsed['name'],
        description=parsed['description'],
        personality=parsed['personality'],
        portrait_path=f"/static/uploads/characters/{char_id}/portrait.png",
        first_message=parsed['first_message'],
        scenario=parsed['scenario'],
        example_dialogs=parsed['example_dialogs'],
        tags=parsed['tags'],
        gender=parsed.get('gender'),
        age=parsed.get('age'),
        occupation=parsed.get('occupation'),
        raw_card_data=parsed['raw_card_data'],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    session.add(character)
    await session.commit()
    
    return {
        "success": True,
        "id": char_id,
        "name": parsed['name'],
        "message": f"成功导入角色: {parsed['name']}"
    }


@router.get("/characters/{char_id}")
async def get_character(
    char_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取角色模板详情"""
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    return {
        "id": character.id,
        "name": character.name,
        "description": character.description,
        "personality": character.personality,
        "portrait_path": character.portrait_path,
        "first_message": character.first_message,
        "scenario": character.scenario,
        "example_dialogs": character.example_dialogs,
        "tags": character.tags,
        "is_player_avatar": character.is_player_avatar,
        "initial_attributes": character.initial_attributes,
        "raw_card_data": character.raw_card_data,
        "created_at": character.created_at.isoformat() if character.created_at else None,
        "updated_at": character.updated_at.isoformat() if character.updated_at else None,
    }


@router.put("/characters/{char_id}")
async def update_character(
    char_id: str,
    data: CharacterTemplateUpdate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """更新角色模板"""
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 更新非 None 字段
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(character, key, value)
    
    character.updated_at = datetime.utcnow()
    session.add(character)
    await session.commit()
    
    return {"success": True}


@router.delete("/characters/{char_id}")
async def delete_character(
    char_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """删除角色模板"""
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 删除关联的图片文件
    if character.portrait_path:
        portrait_dir = UPLOAD_DIR / "characters" / char_id
        if portrait_dir.exists():
            import shutil
            shutil.rmtree(portrait_dir)
    
    await session.delete(character)
    await session.commit()
    
    return {"success": True}


@router.get("/characters/{char_id}/export")
async def export_character_png(
    char_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """导出角色为 PNG（带元数据）"""
    from fastapi.responses import Response
    
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 读取原始图片
    if character.portrait_path:
        portrait_file = Path(__file__).parent.parent.parent / character.portrait_path.lstrip('/')
        if portrait_file.exists():
            png_data = portrait_file.read_bytes()
        else:
            raise HTTPException(status_code=404, detail="立绘文件不存在")
    else:
        raise HTTPException(status_code=400, detail="该角色没有立绘")
    
    # 始终使用当前数据库中的最新数据创建角色卡（而不是可能过时的 raw_card_data）
    # 这样导出的文件总是包含最新的编辑信息
    card_data = create_character_card(
        name=character.name,
        description=character.description,
        personality=character.personality,
        first_message=character.first_message or "",
        scenario=character.scenario or "",
        example_dialogs=character.example_dialogs or [],
        tags=character.tags or [],
        gender=character.gender,
        age=character.age,
        occupation=character.occupation,
    )
    
    # 可选：更新 raw_card_data 以便下次导入时保持一致
    # 但导出时始终使用最新数据
    character.raw_card_data = card_data
    session.add(character)
    await session.commit()
    
    # 嵌入元数据（使用 location key）
    output_png = embed_location_to_png(png_data, card_data)
    
    # 对中文文件名进行 URL 编码，使用 RFC 5987 规范
    filename_encoded = quote(f"{character.name}.png")
    return Response(
        content=output_png,
        media_type="image/png",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )


@router.post("/characters/{char_id}/portrait")
async def upload_character_portrait(
    char_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """上传/更新角色立绘"""
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        raise HTTPException(status_code=400, detail="只支持 PNG/JPG/WEBP 格式")
    
    # 保存图片
    portrait_dir = UPLOAD_DIR / "characters" / char_id
    portrait_dir.mkdir(parents=True, exist_ok=True)
    
    ext = Path(file.filename).suffix
    portrait_path = portrait_dir / f"portrait{ext}"
    content = await file.read()
    portrait_path.write_bytes(content)
    
    # 更新数据库
    character.portrait_path = f"/static/uploads/characters/{char_id}/portrait{ext}"
    character.updated_at = datetime.utcnow()
    session.add(character)
    await session.commit()
    
    return {"success": True, "portrait_path": character.portrait_path}


@router.post("/characters/{char_id}/generate-portrait")
async def generate_character_portrait_endpoint(
    char_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """使用 AI 生成角色立绘"""
    character = await session.get(CharacterTemplate, char_id)
    if not character:
        raise HTTPException(status_code=404, detail="角色不存在")
    
    # 生成立绘
    portrait_image = await generate_character_portrait(
        character.name,
        character.description or "",
        character.personality or ""
    )
    
    if not portrait_image:
        raise HTTPException(status_code=500, detail="立绘生成失败，请检查 OpenAI API 配置")
    
    # 保存立绘
    portrait_dir = UPLOAD_DIR / "characters" / char_id
    portrait_dir.mkdir(parents=True, exist_ok=True)
    portrait_file = portrait_dir / "portrait.png"
    
    if await save_image(portrait_image, portrait_file, "png"):
        portrait_path = f"/static/uploads/characters/{char_id}/portrait.png"
        character.portrait_path = portrait_path
        character.updated_at = datetime.utcnow()
        session.add(character)
        await session.commit()
        
        return {"success": True, "portrait_path": portrait_path}
    else:
        raise HTTPException(status_code=500, detail="立绘保存失败")


# ============== 场景模板管理 ==============

@router.get("/locations")
async def list_locations(
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取所有场景模板"""
    statement = select(LocationTemplate).order_by(LocationTemplate.created_at.desc())
    results = await session.execute(statement)
    locations = results.scalars().all()
    
    return {
        "locations": [
            {
                "id": loc.id,
                "name": loc.name,
                "description": loc.description,
                "background_path": loc.background_path,
                "tags": loc.tags,
                "is_starting_location": loc.is_starting_location,
                "created_at": loc.created_at.isoformat() if loc.created_at else None,
            }
            for loc in locations
        ]
    }


@router.post("/locations/import", response_model=Dict[str, Any])
async def import_location_png(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """从 PNG 导入场景"""
    if not file.filename.lower().endswith('.png'):
        raise HTTPException(status_code=400, detail="只支持 PNG 文件")
    
    # 读取文件
    content = await file.read()
    
    # 提取元数据
    from app.services.chub_parser import extract_location_from_png, parse_location_card
    
    location_data = extract_location_from_png(content)
    if not location_data:
        raise HTTPException(status_code=400, detail="PNG 文件中没有找到场景卡数据")
    
    # 解析场景卡
    parsed = parse_location_card(location_data)
    
    # 保存图片
    loc_id = f"loc_{uuid.uuid4().hex[:8]}"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    bg_dir = UPLOAD_DIR / "locations" / loc_id
    bg_dir.mkdir(parents=True, exist_ok=True)
    bg_path = bg_dir / "background.png"
    bg_path.write_bytes(content)
    
    # 创建数据库记录
    location = LocationTemplate(
        id=loc_id,
        name=parsed['name'],
        description=parsed['description'],
        tags=parsed['tags'],
        background_path=f"/static/uploads/locations/{loc_id}/background.png",
        default_connections=parsed.get('default_connections', []),
        is_starting_location=False,
        raw_card_data=parsed['raw_card_data'],
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    session.add(location)
    await session.commit()
    
    return {
        "success": True,
        "id": loc_id,
        "name": parsed['name'],
        "message": f"成功导入场景: {parsed['name']}"
    }


@router.post("/locations")
async def create_location(
    data: LocationTemplateCreate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """创建场景模板"""
    location = LocationTemplate(
        id=f"loc_{uuid.uuid4().hex[:8]}",
        name=data.name,
        description=data.description,
        tags=data.tags,
        default_connections=data.default_connections,
        default_characters=data.default_characters,
        is_starting_location=data.is_starting_location,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    
    session.add(location)
    await session.commit()
    
    return {"success": True, "id": location.id}


@router.get("/locations/{loc_id}")
async def get_location(
    loc_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取场景模板详情"""
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    return {
        "id": location.id,
        "name": location.name,
        "description": location.description,
        "background_path": location.background_path,
        "tags": location.tags,
        "default_connections": location.default_connections,
        "default_characters": location.default_characters,
        "is_starting_location": location.is_starting_location,
        "raw_card_data": location.raw_card_data,
        "created_at": location.created_at.isoformat() if location.created_at else None,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,
    }


@router.put("/locations/{loc_id}")
async def update_location(
    loc_id: str,
    data: LocationTemplateUpdate,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """更新场景模板"""
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(location, key, value)
    
    location.updated_at = datetime.utcnow()
    session.add(location)
    await session.commit()
    
    return {"success": True}


@router.delete("/locations/{loc_id}")
async def delete_location(
    loc_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """删除场景模板"""
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 删除关联的图片文件
    if location.background_path:
        bg_dir = UPLOAD_DIR / "locations" / loc_id
        if bg_dir.exists():
            import shutil
            shutil.rmtree(bg_dir)
    
    await session.delete(location)
    await session.commit()
    
    return {"success": True}


@router.post("/locations/{loc_id}/background")
async def upload_location_background(
    loc_id: str,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """上传/更新场景背景图"""
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.webp')):
        raise HTTPException(status_code=400, detail="只支持 PNG/JPG/WEBP 格式")
    
    # 保存图片
    bg_dir = UPLOAD_DIR / "locations" / loc_id
    bg_dir.mkdir(parents=True, exist_ok=True)
    
    ext = Path(file.filename).suffix
    bg_path = bg_dir / f"background{ext}"
    content = await file.read()
    bg_path.write_bytes(content)
    
    # 更新数据库
    location.background_path = f"/static/uploads/locations/{loc_id}/background{ext}"
    location.updated_at = datetime.utcnow()
    session.add(location)
    await session.commit()
    
    return {"success": True, "background_path": location.background_path}


@router.post("/locations/{loc_id}/generate-background")
async def generate_location_background_endpoint(
    loc_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """使用 AI 生成场景背景"""
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 生成背景
    bg_image = await generate_scene_background(
        location.name,
        location.description or ""
    )
    
    if not bg_image:
        raise HTTPException(status_code=500, detail="背景生成失败，请检查 OpenAI API 配置")
    
    # 保存背景
    bg_dir = UPLOAD_DIR / "locations" / loc_id
    bg_dir.mkdir(parents=True, exist_ok=True)
    bg_file = bg_dir / "background.jpg"
    
    if await save_image(bg_image, bg_file, "jpg"):
        background_path = f"/static/uploads/locations/{loc_id}/background.jpg"
        location.background_path = background_path
        location.updated_at = datetime.utcnow()
        session.add(location)
        await session.commit()
        
        return {"success": True, "background_path": background_path}
    else:
        raise HTTPException(status_code=500, detail="背景保存失败")


@router.get("/locations/{loc_id}/export")
async def export_location_png(
    loc_id: str,
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """导出场景为 PNG（带元数据）"""
    from fastapi.responses import Response
    
    location = await session.get(LocationTemplate, loc_id)
    if not location:
        raise HTTPException(status_code=404, detail="场景不存在")
    
    # 读取背景图片
    if location.background_path:
        bg_file = Path(__file__).parent.parent.parent / location.background_path.lstrip('/')
        if bg_file.exists():
            png_data = bg_file.read_bytes()
        else:
            raise HTTPException(status_code=404, detail="背景图片不存在")
    else:
        raise HTTPException(status_code=400, detail="该场景没有背景图片")
    
    # 始终使用当前数据库中的最新数据创建场景卡（而不是可能过时的 raw_card_data）
    card_data = create_location_card(
        name=location.name,
        description=location.description,
        tags=location.tags or [],
        default_connections=location.default_connections or [],
        default_characters=location.default_characters or [],
    )
    
    # 可选：更新 raw_card_data 以便下次导入时保持一致
    location.raw_card_data = card_data
    session.add(location)
    await session.commit()
    
    # 嵌入元数据（使用 location key）
    output_png = embed_location_to_png(png_data, card_data)
    
    # 对中文文件名进行 URL 编码
    filename_encoded = quote(f"{location.name}.png")
    return Response(
        content=output_png,
        media_type="image/png",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{filename_encoded}"
        }
    )


# ============== 世界规则管理 ==============

@router.get("/world/rules")
async def get_world_rules(
    world_id: str = "world_1",
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取世界规则"""
    world = await session.get(World, world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    
    return {
        "world_id": world.id,
        "world_name": world.name,
        "rules": world.rules or []
    }


@router.put("/world/rules")
async def update_world_rules(
    data: WorldRulesUpdate,
    world_id: str = "world_1",
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """更新世界规则"""
    world = await session.get(World, world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    
    world.rules = data.rules
    session.add(world)
    await session.commit()
    
    return {"success": True}


@router.get("/world/economy")
async def get_economy_config(
    world_id: str = "world_1",
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """获取经济系统配置"""
    world = await session.get(World, world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    
    return {
        "world_id": world.id,
        "currency_name": world.currency_name,
        "gem_name": world.gem_name,
        "currency_rules": world.currency_rules or ""
    }


@router.put("/world/economy")
async def update_economy_config(
    data: EconomyConfigUpdate,
    world_id: str = "world_1",
    session: AsyncSession = Depends(get_session),
    _: bool = Depends(verify_admin_token)
):
    """更新经济系统配置"""
    world = await session.get(World, world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    
    if data.currency_name is not None:
        world.currency_name = data.currency_name
    if data.gem_name is not None:
        world.gem_name = data.gem_name
    if data.currency_rules is not None:
        world.currency_rules = data.currency_rules
    
    session.add(world)
    await session.commit()
    
    return {"success": True}


# ============== 玩家 Avatar ==============

@router.get("/avatars")
async def list_avatars(
    session: AsyncSession = Depends(get_session)
):
    """获取可选的玩家 Avatar 列表（不需要认证）"""
    statement = select(CharacterTemplate).where(CharacterTemplate.is_player_avatar == True)
    results = await session.execute(statement)
    avatars = results.scalars().all()
    
    return {
        "avatars": [
            {
                "id": a.id,
                "name": a.name,
                "description": a.description,
                "portrait_path": a.portrait_path,
                "personality": a.personality,
                "initial_attributes": a.initial_attributes,
            }
            for a in avatars
        ]
    }


@router.post("/avatar/select")
async def select_avatar(
    data: dict,
    session: AsyncSession = Depends(get_session)
):
    """选择 Avatar 并创建/更新玩家（不需要认证）"""
    import random
    from app.models.schemas import Player, Location
    
    template_id = data.get("template_id")
    player_name = data.get("player_name")
    world_id = data.get("world_id", "world_1")
    player_id = data.get("player_id", "player_1")
    
    if not template_id or not player_name:
        raise HTTPException(status_code=400, detail="缺少必要参数")
    
    # 获取角色模板
    template = await session.get(CharacterTemplate, template_id)
    if not template:
        raise HTTPException(status_code=404, detail="角色模板不存在")
    
    if not template.is_player_avatar:
        raise HTTPException(status_code=400, detail="该角色不可作为玩家形象")
    
    # 随机选择初始场景
    # 1. 先查 Location 表中标记为初始场景的
    starting_loc_statement = select(Location).where(
        Location.world_id == world_id,
        Location.is_starting_location == True
    )
    starting_loc_result = await session.execute(starting_loc_statement)
    starting_locations = list(starting_loc_result.scalars().all())
    
    # 2. 如果 Location 表没有初始场景，从 LocationTemplate 模板创建
    if not starting_locations:
        starting_template_statement = select(LocationTemplate).where(
            LocationTemplate.is_starting_location == True
        )
        starting_template_result = await session.execute(starting_template_statement)
        starting_templates = list(starting_template_result.scalars().all())
        
        # 从模板创建 Location 记录
        for tpl in starting_templates:
            new_location = Location(
                id=f"loc_{tpl.id}",  # 使用模板ID作为前缀
                world_id=world_id,
                name=tpl.name,
                description=tpl.description,
                background_url=tpl.background_path,
                connections=[],
                is_starting_location=True
            )
            session.add(new_location)
            starting_locations.append(new_location)
        
        if starting_templates:
            await session.flush()  # 确保新记录有效
    
    if starting_locations:
        # 随机选择一个初始场景
        location = random.choice(starting_locations)
    else:
        # 还是没有初始场景，使用任意场景
        loc_statement = select(Location).where(Location.world_id == world_id).limit(1)
        loc_result = await session.execute(loc_statement)
        location = loc_result.scalar_one_or_none()
    
    if not location:
        raise HTTPException(status_code=400, detail="世界中没有可用的位置")
    
    # 检查玩家是否存在
    player = await session.get(Player, player_id)
    
    if player:
        # 更新现有玩家
        player.name = player_name
        player.avatar_template_id = template_id
        player.portrait_url = template.portrait_path
        player.personality = template.personality
        player.background = template.scenario
        player.attributes = template.initial_attributes or {}
        player.location_id = location.id  # 更新到初始场景
    else:
        # 创建新玩家
        player = Player(
            id=player_id,
            world_id=world_id,
            name=player_name,
            location_id=location.id,
            avatar_template_id=template_id,
            portrait_url=template.portrait_path,
            personality=template.personality,
            background=template.scenario,
            attributes=template.initial_attributes or {},
        )
    
    session.add(player)
    await session.commit()
    
    return {
        "success": True,
        "player": {
            "id": player.id,
            "name": player.name,
            "portrait_url": player.portrait_url,
        },
        "starting_location": {
            "id": location.id,
            "name": location.name,
            "background_url": location.background_url,
        }
    }
