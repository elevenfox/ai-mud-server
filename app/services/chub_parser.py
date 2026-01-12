"""Chub.ai PNG 角色卡解析器

支持读取和写入 PNG 图片中嵌入的 Character Card V2 元数据。
元数据存储在 PNG 的 tEXt chunk 中，key 为 'chara'，value 为 base64 编码的 JSON。
"""

import base64
import json
import struct
import zlib
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
from io import BytesIO


def read_png_chunks(data: bytes) -> list:
    """读取 PNG 文件的所有 chunks"""
    chunks = []
    
    # 跳过 PNG 签名 (8 bytes)
    pos = 8
    
    while pos < len(data):
        # 读取 chunk 长度 (4 bytes, big-endian)
        length = struct.unpack('>I', data[pos:pos+4])[0]
        pos += 4
        
        # 读取 chunk 类型 (4 bytes)
        chunk_type = data[pos:pos+4].decode('ascii')
        pos += 4
        
        # 读取 chunk 数据
        chunk_data = data[pos:pos+length]
        pos += length
        
        # 跳过 CRC (4 bytes)
        pos += 4
        
        chunks.append({
            'type': chunk_type,
            'data': chunk_data
        })
        
        if chunk_type == 'IEND':
            break
    
    return chunks


def write_png_chunks(chunks: list) -> bytes:
    """将 chunks 写入 PNG 格式"""
    # PNG 签名
    output = b'\x89PNG\r\n\x1a\n'
    
    for chunk in chunks:
        chunk_type = chunk['type'].encode('ascii')
        chunk_data = chunk['data']
        length = len(chunk_data)
        
        # 写入长度
        output += struct.pack('>I', length)
        # 写入类型
        output += chunk_type
        # 写入数据
        output += chunk_data
        # 计算并写入 CRC
        crc = zlib.crc32(chunk_type + chunk_data) & 0xffffffff
        output += struct.pack('>I', crc)
    
    return output


def extract_chara_from_png(png_data: bytes) -> Optional[Dict[str, Any]]:
    """从 PNG 文件中提取 Chub.ai 角色卡数据
    
    Args:
        png_data: PNG 文件的二进制数据
        
    Returns:
        角色卡 JSON 数据，如果不存在则返回 None
    """
    try:
        chunks = read_png_chunks(png_data)
        
        for chunk in chunks:
            if chunk['type'] == 'tEXt':
                # tEXt chunk 格式: keyword\0text
                data = chunk['data']
                null_pos = data.find(b'\x00')
                if null_pos != -1:
                    keyword = data[:null_pos].decode('latin-1')
                    if keyword == 'chara':
                        text = data[null_pos+1:].decode('latin-1')
                        # Base64 解码
                        json_data = base64.b64decode(text).decode('utf-8')
                        return json.loads(json_data)
        
        return None
    except Exception as e:
        print(f"Error extracting chara data: {e}")
        return None


def embed_chara_to_png(png_data: bytes, chara_data: Dict[str, Any]) -> bytes:
    """将角色卡数据嵌入到 PNG 文件中
    
    Args:
        png_data: 原始 PNG 文件的二进制数据（或 JPG，会自动转换）
        chara_data: 角色卡 JSON 数据
        
    Returns:
        带有嵌入数据的新 PNG 文件二进制数据
    """
    # 检查是否为 PNG 格式
    is_png = png_data.startswith(b'\x89PNG\r\n\x1a\n')
    
    if not is_png:
        # 可能是 JPG 或其他格式，尝试转换为 PNG
        try:
            from PIL import Image
            from io import BytesIO
        except ImportError:
            raise ValueError(
                "PIL/Pillow not installed. Cannot convert non-PNG images to PNG. "
                "Please install Pillow: pip install Pillow"
            )
        
        try:
            img = Image.open(BytesIO(png_data))
            # 转换为 RGB（如果是 RGBA）
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            
            # 转换为 PNG bytes
            png_buffer = BytesIO()
            img.save(png_buffer, format='PNG')
            png_data = png_buffer.getvalue()
        except Exception as e:
            raise ValueError(f"Failed to convert image to PNG: {e}")
    
    # 尝试读取 PNG chunks
    try:
        chunks = read_png_chunks(png_data)
    except Exception as e:
        raise ValueError(f"Failed to read PNG chunks: {e}. The file may be corrupted or not a valid PNG.")
    
    # 检查是否有 IEND chunk
    iend_indices = [i for i, c in enumerate(chunks) if c['type'] == 'IEND']
    if not iend_indices:
        raise ValueError("Invalid PNG file: missing IEND chunk")
    
    # 移除已有的 chara tEXt chunk
    chunks = [c for c in chunks if not (c['type'] == 'tEXt' and c['data'].startswith(b'chara\x00'))]
    
    # 重新查找 IEND（因为可能被移除了）
    iend_indices = [i for i, c in enumerate(chunks) if c['type'] == 'IEND']
    if not iend_indices:
        raise ValueError("Invalid PNG file: missing IEND chunk after cleanup")
    
    # 创建新的 tEXt chunk
    json_str = json.dumps(chara_data, ensure_ascii=False)
    base64_data = base64.b64encode(json_str.encode('utf-8')).decode('latin-1')
    text_data = b'chara\x00' + base64_data.encode('latin-1')
    
    # 在最后一个 IEND 之前插入 tEXt chunk
    iend_index = iend_indices[-1]
    chunks.insert(iend_index, {'type': 'tEXt', 'data': text_data})
    
    return write_png_chunks(chunks)


def parse_character_card(chara_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析 Character Card V2 格式的数据，转换为内部格式
    
    Character Card V2 spec 主要字段:
    - name: 角色名称
    - description: 角色描述
    - personality: 性格
    - first_mes: 首次消息
    - mes_example: 对话示例
    - scenario: 场景/背景
    - creator_notes: 创建者备注
    - system_prompt: 系统提示
    - post_history_instructions: 历史后指令
    - alternate_greetings: 替代问候语
    - tags: 标签
    - creator: 创建者
    - character_version: 版本
    - extensions: 扩展数据
    """
    # V2 格式
    if 'data' in chara_data:
        data = chara_data['data']
    else:
        # V1 格式或直接数据
        data = chara_data
    
    # 处理对话示例 - 分割成列表
    mes_example = data.get('mes_example', '') or ''
    example_dialogs = []
    if mes_example:
        # 尝试按 <START> 分割
        if '<START>' in mes_example:
            parts = mes_example.split('<START>')
            example_dialogs = [p.strip() for p in parts if p.strip()]
        else:
            example_dialogs = [mes_example.strip()]
    
    return {
        'name': data.get('name', 'Unknown'),
        'description': data.get('description', ''),
        'personality': data.get('personality', ''),
        'first_message': data.get('first_mes', ''),
        'scenario': data.get('scenario', ''),
        'example_dialogs': example_dialogs,
        'tags': data.get('tags', []),
        'raw_card_data': chara_data,  # 保留原始数据用于导出
    }


def create_character_card(
    name: str,
    description: str = "",
    personality: str = "",
    first_message: str = "",
    scenario: str = "",
    example_dialogs: list = None,
    tags: list = None,
    **kwargs
) -> Dict[str, Any]:
    """创建 Character Card V2 格式的数据
    
    Returns:
        可用于嵌入 PNG 的角色卡数据
    """
    # 将对话示例列表转换为字符串格式
    mes_example = ""
    if example_dialogs:
        mes_example = "\n<START>\n".join(example_dialogs)
    
    return {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": name,
            "description": description,
            "personality": personality,
            "first_mes": first_message,
            "mes_example": mes_example,
            "scenario": scenario,
            "creator_notes": "",
            "system_prompt": "",
            "post_history_instructions": "",
            "alternate_greetings": [],
            "tags": tags or [],
            "creator": "AI MUD",
            "character_version": "1.0",
            "extensions": kwargs
        }
    }


def create_location_card(
    name: str,
    description: str = "",
    tags: list = None,
    default_connections: list = None,
    default_characters: list = None,
    **kwargs
) -> Dict[str, Any]:
    """创建场景卡数据（自定义格式，类似角色卡）
    
    Returns:
        可用于嵌入 PNG 的场景卡数据
    """
    return {
        "spec": "location_card_v1",
        "spec_version": "1.0",
        "data": {
            "name": name,
            "description": description,
            "tags": tags or [],
            "default_connections": default_connections or [],
            "default_characters": default_characters or [],
            "creator": "AI MUD",
            "extensions": kwargs
        }
    }


def parse_location_card(card_data: Dict[str, Any]) -> Dict[str, Any]:
    """解析场景卡数据"""
    if 'data' in card_data:
        data = card_data['data']
    else:
        data = card_data
    
    return {
        'name': data.get('name', 'Unknown Location'),
        'description': data.get('description', ''),
        'tags': data.get('tags', []),
        'default_connections': data.get('default_connections', []),
        'default_characters': data.get('default_characters', []),
        'raw_card_data': card_data,
    }
