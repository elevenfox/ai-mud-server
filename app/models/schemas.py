from typing import List, Optional, Dict, Any
from sqlmodel import SQLModel, Field, JSON, Column
from datetime import datetime
from pydantic import BaseModel

# ============== Database Models ==============

class World(SQLModel, table=True):
    id: str = Field(primary_key=True)
    time: int = 0
    seed: int = 42
    name: str = "Unnamed World"
    description: str = ""
    # 世界规则，AI 必须遵守
    rules: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 存储世界标志位，如 {"has_key": True}
    flags: Dict[str, bool] = Field(default_factory=dict, sa_column=Column(JSON))
    # 当前 BGM mood
    current_mood: str = "neutral"  # neutral, tense, calm, mysterious, action

class Location(SQLModel, table=True):
    id: str = Field(primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    name: str
    description: str
    background_url: Optional[str] = None
    # 相连地点的 ID 列表
    connections: List[str] = Field(default_factory=list, sa_column=Column(JSON))

class NPC(SQLModel, table=True):
    id: str = Field(primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    name: str
    description: str
    personality: str
    location_id: str = Field(foreign_key="location.id")
    portrait_url: Optional[str] = None
    # Chub.ai 角色卡字段
    first_message: Optional[str] = None  # NPC 首次见面的开场白
    scenario: Optional[str] = None       # NPC 的背景故事/情境
    example_dialogs: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 当前情绪状态
    current_emotion: str = "default"  # default, happy, angry, sad, surprised
    # 与玩家的关系值 (-100 到 100)
    relationship: int = 0

class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    name: str
    location_id: str = Field(foreign_key="location.id")
    inventory: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # Avatar 相关
    avatar_template_id: Optional[str] = None  # 关联的角色模板 ID
    portrait_url: Optional[str] = None  # 立绘路径
    personality: Optional[str] = None  # 性格/说话语气
    background: Optional[str] = None  # 背景故事
    attributes: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # 属性

class GameEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    timestamp: int
    event_type: str  # 'move', 'talk', 'observation', 'system', 'choice'
    content: str     # 叙事文本
    # 额外信息，如 {"mood": "tense", "sender": "npc_1"}
    extra_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))


class Conversation(SQLModel, table=True):
    """NPC 对话历史记录"""
    id: Optional[int] = Field(default=None, primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    npc_id: str = Field(foreign_key="npc.id")
    player_id: str = Field(foreign_key="player.id")
    timestamp: int
    role: str  # 'player' or 'npc'
    content: str


class Checkpoint(SQLModel, table=True):
    """存档点"""
    id: str = Field(primary_key=True)
    world_id: str = Field(foreign_key="world.id")
    player_id: str = Field(foreign_key="player.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    description: str = ""
    # 完整世界状态快照
    world_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # 是否为自动存档
    is_auto: bool = False


# ============== 模板库 (Admin 管理) ==============

class CharacterTemplate(SQLModel, table=True):
    """角色模板 - 可用于创建 NPC 或玩家 Avatar"""
    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    personality: str = ""
    # 立绘图片路径
    portrait_path: Optional[str] = None
    # Chub.ai 角色卡字段
    first_message: Optional[str] = None
    scenario: Optional[str] = None
    example_dialogs: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 标签/分类
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 是否可作为玩家 Avatar 选择
    is_player_avatar: bool = False
    # 初始属性（用于玩家 Avatar）
    initial_attributes: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # 原始 Chub.ai 卡片数据（用于导出）
    raw_card_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # 创建时间
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LocationTemplate(SQLModel, table=True):
    """场景模板 - 可用于创建游戏地点"""
    id: str = Field(primary_key=True)
    name: str
    description: str = ""
    # 背景图片路径
    background_path: Optional[str] = None
    # 标签/分类
    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 默认连接的场景 ID 列表（模板 ID）
    default_connections: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 默认放置的角色模板 ID 列表
    default_characters: List[str] = Field(default_factory=list, sa_column=Column(JSON))
    # 原始卡片数据（用于导出）
    raw_card_data: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    # 创建时间
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ============== API Request/Response Models ==============

class Choice(BaseModel):
    """单个选项"""
    id: str
    text: str
    # 选择此选项可能导致的情绪/后果提示 (可选)
    hint: Optional[str] = None


class ChoicesResponse(BaseModel):
    """选项生成响应"""
    narrative: str  # 当前情境描述
    choices: List[Choice]
    allow_custom: bool = True  # 是否允许自由输入
    mood: str = "neutral"  # BGM mood 提示


class ActionResult(BaseModel):
    """行动结果"""
    success: bool
    narrative: str
    choices: Optional[List[Choice]] = None
    mood: str = "neutral"
    npc_emotion: Optional[str] = None
    location_changed: bool = False
    new_location: Optional[str] = None


class JudgeResult(BaseModel):
    """Judge 校验结果"""
    allowed: bool
    reason: Optional[str] = None
    suggested_action: Optional[str] = None


# ============== Admin API Models ==============

class AdminLoginRequest(BaseModel):
    """Admin 登录请求"""
    password: str


class AdminLoginResponse(BaseModel):
    """Admin 登录响应"""
    success: bool
    token: Optional[str] = None
    message: Optional[str] = None


class CharacterTemplateCreate(BaseModel):
    """创建角色模板请求"""
    name: str
    description: str = ""
    personality: str = ""
    first_message: Optional[str] = None
    scenario: Optional[str] = None
    example_dialogs: List[str] = []
    tags: List[str] = []
    is_player_avatar: bool = False
    initial_attributes: Dict[str, Any] = {}


class CharacterTemplateUpdate(BaseModel):
    """更新角色模板请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    personality: Optional[str] = None
    first_message: Optional[str] = None
    scenario: Optional[str] = None
    example_dialogs: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    is_player_avatar: Optional[bool] = None
    initial_attributes: Optional[Dict[str, Any]] = None


class LocationTemplateCreate(BaseModel):
    """创建场景模板请求"""
    name: str
    description: str = ""
    tags: List[str] = []
    default_connections: List[str] = []
    default_characters: List[str] = []


class LocationTemplateUpdate(BaseModel):
    """更新场景模板请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    default_connections: Optional[List[str]] = None
    default_characters: Optional[List[str]] = None


class WorldRulesUpdate(BaseModel):
    """更新世界规则请求"""
    rules: List[str]


class AvatarSelection(BaseModel):
    """玩家选择 Avatar 请求"""
    template_id: str
    player_name: str
