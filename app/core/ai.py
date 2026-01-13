import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

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
        
        print(f"🔧 使用本地 LLM API: {base_url}")
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "not-needed"),  # 本地 LLM 可能不需要 key
            base_url=base_url,
            timeout=60.0  # 增加超时时间，本地 LLM 可能较慢
        )
    else:
        # 使用 OpenAI API
        print("🔧 使用 OpenAI API")
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    client = None
    print("🔧 使用 MOCK 模式")


async def generate_narrative(system_prompt: str, user_prompt: str) -> str:
    """通用 AI 文本生成"""
    if MOCK_MODE:
        return f"[MOCK] 系统提示: {system_prompt[:50]}... | 用户: {user_prompt[:50]}..."
    
    response = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7
    )
    return response.choices[0].message.content


async def generate_json(system_prompt: str, user_prompt: str, schema_hint: str = "") -> Dict[str, Any]:
    """生成结构化 JSON 输出"""
    if MOCK_MODE:
        # Mock 返回示例数据
        return {
            "choices": [
                {"id": "1", "text": "[MOCK] 选项 A: 继续调查"},
                {"id": "2", "text": "[MOCK] 选项 B: 离开这里"},
                {"id": "3", "text": "[MOCK] 选项 C: 与 NPC 交谈"}
            ],
            "narrative": "[MOCK] 这是一段叙事文本...",
            "mood": "neutral",
            "character_positions": {
                "player": "right"
            }
        }
    
    full_system = f"{system_prompt}\n\n你必须只返回有效的 JSON。{schema_hint}"
    
    try:
        # 构建请求参数
        request_params = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "messages": [
                {"role": "system", "content": full_system},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.7
        }
        # 本地 LLM 可能不支持 response_format，完全不传递该参数
        if not LOCAL_LLM:
            request_params["response_format"] = {"type": "json_object"}
        
        response = await client.chat.completions.create(**request_params)
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        error_msg = str(e)
        if LOCAL_LLM:
            print(f"❌ 本地 LLM 连接错误: {error_msg}")
            print(f"   请检查:")
            print(f"   1. LOCAL_LLM={LOCAL_LLM} 是否正确")
            print(f"   2. 本地 LLM 服务是否正在运行")
            print(f"   3. URL 是否可以访问（尝试: curl {LOCAL_LLM.rstrip('/')}/v1/models）")
        else:
            print(f"❌ OpenAI API 连接错误: {error_msg}")
        raise


async def generate_npc_response(
    npc_name: str,
    npc_personality: str,
    npc_description: str,
    scenario: Optional[str],
    example_dialogs: List[str],
    conversation_history: List[Dict[str, str]],
    player_message: str,
    world_context: str
) -> Dict[str, Any]:
    """NPC 独立人格对话生成"""
    
    # 构建 NPC 系统提示（中文版）
    system_prompt = f"""你是 {npc_name}，一个 MUD 游戏中的角色。请用中文回复。

性格特点: {npc_personality}

外貌描述: {npc_description}

{f'背景故事: {scenario}' if scenario else ''}

{f'对话风格示例:{chr(10).join(example_dialogs[:3])}' if example_dialogs else ''}

世界背景: {world_context}

玩家输入格式说明：
- *星号包裹* = 玩家的动作（例如：*微微点头*）
- "双引号" = 玩家说的话（例如："你好"）
- （圆括号）= 玩家给AI的指示，不是角色对话
- ~波浪号~ = 拖长音

规则:
- 完全保持 {npc_name} 的角色
- 你的回复应该反映你的性格特点
- 保持简洁（通常2-4句话）
- 你可以表达会影响立绘的情绪
- 理解玩家的动作并做出相应反应

你的回复格式：
- 用 *星号* 包裹你的动作和表情
- 用 "引号" 或不带引号直接回复对话

用 JSON 格式回复:
{{
    "response": "你的角色内回复（可混合动作和对话，如：*微笑* \\"当然可以。\\"）",
    "emotion": "default|happy|angry|sad|surprised|fearful",
    "relationship_change": -5 到 +5（这次互动如何影响你对玩家的感觉）,
    "internal_thought": "简短的内心独白（不会显示给玩家）"
}}"""

    # 构建对话历史
    messages = [{"role": "system", "content": system_prompt}]
    for msg in conversation_history[-10:]:  # 最近 10 条
        role = "assistant" if msg["role"] == "npc" else "user"
        messages.append({"role": role, "content": msg["content"]})
    messages.append({"role": "user", "content": player_message})
    
    if MOCK_MODE:
        return {
            "response": f"[MOCK] {npc_name}: 我听到你说了「{player_message[:20]}...」",
            "emotion": "default",
            "relationship_change": 0,
            "internal_thought": "[MOCK] 内心想法..."
        }
    
    # 构建请求参数
    request_params = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "messages": messages,
        "temperature": 0.8
    }
    # 本地 LLM 可能不支持 response_format，完全不传递该参数
    if not LOCAL_LLM:
        request_params["response_format"] = {"type": "json_object"}
    
    response = await client.chat.completions.create(**request_params)
    return json.loads(response.choices[0].message.content)


async def generate_choices(
    world_rules: List[str],
    current_situation: str,
    recent_events: List[str],
    player_stats: Dict[str, Any],
    available_actions: List[str],
    npcs_in_scene: List[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """生成玩家选项，同时决定角色在场景中的位置"""
    
    # 构建 NPC 信息
    npc_info = ""
    if npcs_in_scene:
        npc_names = [npc.get("name", "未知") for npc in npcs_in_scene]
        npc_info = f"\n当前场景中的 NPC: {', '.join(npc_names)}"
    
    system_prompt = """你是一个 MUD 游戏的游戏大师。为玩家生成有意义的选项，并像视觉小说导演一样安排角色在画面中的位置。请用中文回复。

规则:
- 生成 3-4 个不同的、有意义的选项
- 每个选项应该导向不同的叙事路径
- 选项应该符合世界规则
- 至少包含一个「安全」选项和一个「冒险」选项
- 选项应该在当前情境下感觉自然
- 考虑玩家的货币状况，如果选项涉及消费，在 hint 中提示需要的货币类型和数量

经济系统理解:
- 游戏内货币（如"金币"）：用于购买游戏逻辑内的物品、服务、食物等
- 付费货币（如"宝石"）：用于购买不影响游戏平衡的道具，如皮肤、配饰、装饰品等
- 根据货币规则判断消费类型，在选项 hint 中明确说明

角色位置规则（像视觉小说一样）:
- 位置有三个：left（左）、center（中）、right（右）
- 玩家（player）和 NPC 应该根据剧情关系和对话情境安排位置
- 对话时，双方通常面对面（一左一右）
- 重要角色或正在说话的角色可以在中间
- 多个角色时要合理分布

用 JSON 格式回复:
{
    "narrative": "当前时刻/情境的简短描述",
    "choices": [
        {"id": "1", "text": "选项描述", "hint": "关于后果的可选提示"},
        {"id": "2", "text": "选项描述", "hint": null},
        ...
    ],
    "mood": "neutral|tense|calm|mysterious|action",
    "character_positions": {
        "player": "left|center|right",
        "npc_id_1": "left|center|right",
        "npc_id_2": "left|center|right"
    }
}"""

    user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in world_rules)}

当前情境:
{current_situation}{npc_info}

最近事件:
{chr(10).join(f'- {event}' for event in recent_events[-5:])}

玩家状态:
{json.dumps(player_stats, indent=2, ensure_ascii=False)}

可用行动（物理上可能的）:
{chr(10).join(f'- {action}' for action in available_actions)}

{f'场景中的 NPC ID 列表: {[npc.get("id") for npc in npcs_in_scene]}' if npcs_in_scene else '场景中没有 NPC'}

为玩家生成合适的选项，并安排角色的画面位置。"""

    return await generate_json(system_prompt, user_prompt)


# RP 格式说明（供 AI 理解玩家输入）
RP_FORMAT_GUIDE = """
玩家输入格式说明：
- *星号包裹* = 动作或场景描写（例如：*缓缓走近，眼神警惕*）
- "双引号" = 角色说的话（例如："你是谁？"）
- （圆括号）= 玩家意图/OOC指令（例如：（我想去酒吧找线索））
- ~波浪号~ = 拖长音或特殊语气（例如："等一下~"）
- **双星号** = 重点强调

玩家可能混合使用这些格式，例如：
*走向酒保* "来杯最烈的。" *把钱拍在桌上*

你需要理解这些格式，并根据玩家的意图做出响应。
"""


async def suggest_scene_npcs(
    scene_name: str,
    scene_description: str,
    story_context: str,
    available_characters: List[Dict[str, Any]],
    current_npcs: List[str] = None
) -> Dict[str, Any]:
    """
    根据场景和剧情，建议应该出现的 NPC
    
    用于：
    - 场景切换时决定加载哪些角色
    - 剧情发展时引入新角色
    """
    
    system_prompt = """你是一个游戏剧情导演。根据场景和故事发展，建议应该出现哪些角色。请用中文回复。

规则：
- 考虑场景类型和氛围
- 考虑剧情发展的需要
- 不要添加太多角色（1-3 个为宜）
- 如果有合适的现有角色，优先使用
- 只有在必要时才建议创建新角色

用 JSON 格式回复:
{
    "should_add_npcs": true/false,
    "reasoning": "为什么需要/不需要添加角色",
    "suggested_npcs": [
        {
            "action": "use_existing" 或 "create_new",
            "character_id": "如果使用现有角色，填写 ID",
            "role": "角色在剧情中的作用，如：服务员、神秘人",
            "entrance": "角色出场方式描述",
            "new_character": {  // 只有 create_new 时需要
                "name": "角色名",
                "description": "外貌描述",
                "personality": "性格",
                "first_message": "开场白"
            }
        }
    ]
}"""

    # 构建可用角色列表
    chars_text = "无可用角色"
    if available_characters:
        chars_list = [
            f"- {c.get('id')}: {c.get('name')} ({c.get('description', '')[:50]}...)"
            for c in available_characters[:10]
        ]
        chars_text = "\n".join(chars_list)
    
    current_text = "无"
    if current_npcs:
        current_text = ", ".join(current_npcs)
    
    user_prompt = f"""场景：{scene_name}
场景描述：{scene_description}

故事上下文：
{story_context}

当前场景中的角色：{current_text}

可用的角色库：
{chars_text}

这个场景应该有哪些角色？"""

    if MOCK_MODE:
        return {
            "should_add_npcs": False,
            "reasoning": "[MOCK] 当前场景不需要额外角色",
            "suggested_npcs": []
        }
    
    return await generate_json(system_prompt, user_prompt)


async def judge_action(
    world_rules: List[str],
    current_situation: str,
    player_action: str,
    physical_constraints: List[str]
) -> Dict[str, Any]:
    """Judge 模块：校验玩家自由输入是否合法"""
    
    system_prompt = f"""你是 MUD 游戏的规则执行者。你的任务是判断玩家的行动是否被允许。请用中文回复。

{RP_FORMAT_GUIDE}

拒绝的标准:
1. 违反明确的世界规则
2. 在当前约束下物理上不可能
3. 试图操纵游戏系统（元游戏）
4. 不当内容

允许的标准:
1. 创意但合理的行动
2. 符合世界精神的行动
3. 意想不到但有效的玩家能动性

对创意行动要宽容，但对规则违反要严格。
圆括号（）中的内容是玩家的OOC意图，应该尊重但转化为游戏内行动。

用 JSON 回复:
{{
    "allowed": true/false,
    "reason": "如果拒绝，说明原因",
    "suggested_action": "如果拒绝，给出替代建议，如果允许则为 null",
    "modified_action": "如果允许，清理后的行动版本",
    "parsed_intent": {{
        "actions": ["解析出的动作列表"],
        "dialogues": ["解析出的对话列表"],
        "ooc_intent": "玩家的OOC意图（如果有）"
    }}
}}"""

    user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in world_rules)}

当前情境:
{current_situation}

物理约束:
{chr(10).join(f'- {c}' for c in physical_constraints)}

玩家尝试的行动:
「{player_action}」

解析玩家的输入格式，判断这个行动是否允许。"""

    if MOCK_MODE:
        return {
            "allowed": True,
            "reason": None,
            "suggested_action": None,
            "modified_action": player_action,
            "parsed_intent": {
                "actions": [player_action],
                "dialogues": [],
                "ooc_intent": None
            }
        }
    
    # 构建请求参数
    request_params = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3  # 低温度，更确定性
    }
    # 本地 LLM 可能不支持 response_format，完全不传递该参数
    if not LOCAL_LLM:
        request_params["response_format"] = {"type": "json_object"}
    
    response = await client.chat.completions.create(**request_params)
    return json.loads(response.choices[0].message.content)
