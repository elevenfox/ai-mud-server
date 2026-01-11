import os
import json
from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

load_dotenv()

MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"
client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY")) if not MOCK_MODE else None


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
            "mood": "neutral"
        }
    
    full_system = f"{system_prompt}\n\n你必须只返回有效的 JSON。{schema_hint}"
    
    response = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


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

规则:
- 完全保持 {npc_name} 的角色
- 你的回复应该反映你的性格特点
- 保持简洁（通常2-4句话）
- 你可以表达会影响立绘的情绪

用 JSON 格式回复:
{{
    "response": "你的角色内回复",
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
    
    response = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        messages=messages,
        temperature=0.8,
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)


async def generate_choices(
    world_rules: List[str],
    current_situation: str,
    recent_events: List[str],
    player_stats: Dict[str, Any],
    available_actions: List[str]
) -> Dict[str, Any]:
    """生成玩家选项"""
    
    system_prompt = """你是一个 MUD 游戏的游戏大师。为玩家生成有意义的选项。请用中文回复。

规则:
- 生成 3-4 个不同的、有意义的选项
- 每个选项应该导向不同的叙事路径
- 选项应该符合世界规则
- 至少包含一个「安全」选项和一个「冒险」选项
- 选项应该在当前情境下感觉自然

用 JSON 格式回复:
{
    "narrative": "当前时刻/情境的简短描述",
    "choices": [
        {"id": "1", "text": "选项描述", "hint": "关于后果的可选提示"},
        {"id": "2", "text": "选项描述", "hint": null},
        ...
    ],
    "mood": "neutral|tense|calm|mysterious|action"
}"""

    user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in world_rules)}

当前情境:
{current_situation}

最近事件:
{chr(10).join(f'- {event}' for event in recent_events[-5:])}

玩家状态:
{json.dumps(player_stats, indent=2, ensure_ascii=False)}

可用行动（物理上可能的）:
{chr(10).join(f'- {action}' for action in available_actions)}

为玩家生成合适的选项。"""

    return await generate_json(system_prompt, user_prompt)


async def judge_action(
    world_rules: List[str],
    current_situation: str,
    player_action: str,
    physical_constraints: List[str]
) -> Dict[str, Any]:
    """Judge 模块：校验玩家自由输入是否合法"""
    
    system_prompt = """你是 MUD 游戏的规则执行者。你的任务是判断玩家的行动是否被允许。请用中文回复。

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

用 JSON 回复:
{
    "allowed": true/false,
    "reason": "如果拒绝，说明原因",
    "suggested_action": "如果拒绝，给出替代建议，如果允许则为 null",
    "modified_action": "如果允许，清理后的行动版本"
}"""

    user_prompt = f"""世界规则:
{chr(10).join(f'- {rule}' for rule in world_rules)}

当前情境:
{current_situation}

物理约束:
{chr(10).join(f'- {c}' for c in physical_constraints)}

玩家尝试的行动:
「{player_action}」

判断这个行动。"""

    if MOCK_MODE:
        return {
            "allowed": True,
            "reason": None,
            "suggested_action": None,
            "modified_action": player_action
        }
    
    response = await client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,  # 低温度，更确定性
        response_format={"type": "json_object"}
    )
    return json.loads(response.choices[0].message.content)
