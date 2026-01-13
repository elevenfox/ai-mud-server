import os
import json
import re
import json5
from openai import AsyncOpenAI
from dotenv import load_dotenv
from typing import Optional, List, Dict, Any

load_dotenv()


EMOTION_LIST = [
    "neutral",
    "tense",
    "calm",
    "mysterious",
    "action",
    "happy",
    "sad",
    "angry",
    "surprised",
    "fearful",
    "excited",
    "bored",
    "curious",
    "confused",
    "annoyed",
    "satisfied",
    "disappointed"
]

def parse_json_with_fallback(content: str) -> Dict[str, Any]:
    """使用 json5 优先解析 JSON，如果失败则使用标准 json
    
    json5 支持更宽松的 JSON 格式：
    - 允许尾随逗号
    - 允许单引号字符串
    - 允许未转义的换行符（在字符串中）
    - 允许注释
    - 等等
    """
    try:
        # 先尝试使用 json5 解析（更宽松）
        return json5.loads(content)
    except Exception as e:
        # 如果 json5 失败，尝试标准 json
        try:
            return json.loads(content)
        except json.JSONDecodeError as je:
            # 如果都失败，抛出异常（调用者可以使用 repair_json_with_llm 修复）
            raise e


async def repair_json_with_llm(invalid_json: str, expected_schema: Optional[str] = None) -> Dict[str, Any]:
    """使用 LLM 修复无效的 JSON 字符串
    
    Args:
        invalid_json: 无效的 JSON 字符串
        expected_schema: 可选的 JSON schema 描述，帮助 LLM 理解期望的格式
    
    Returns:
        修复后的 JSON 对象
    """
    if MOCK_MODE or client is None:
        raise ValueError("LLM 不可用，无法修复 JSON")
    
    # 构建修复 prompt
    schema_hint = ""
    if expected_schema:
        schema_hint = f"\n期望的 JSON 结构：\n{expected_schema}"
    
    system_prompt = f"""你是一个 JSON 修复专家。你的任务是将无效的 JSON 字符串修复为有效的 JSON。

规则：
1. 只返回修复后的 JSON，不要其他文字
2. 保持原始数据的含义和结构
3. 修复常见的 JSON 错误：
   - 未转义的引号
   - 尾随逗号
   - 中文标点符号（，、：）
   - 控制字符
   - 未闭合的括号
   - 多个 JSON 对象（只保留第一个）
4. 确保所有字符串值都正确转义
5. 确保所有数字、布尔值、null 格式正确{schema_hint}

只返回修复后的 JSON，不要任何解释或额外文本。"""

    user_prompt = f"""请修复以下无效的 JSON：

{invalid_json[:2000]}  # 限制长度避免超出 token 限制

只返回修复后的 JSON，不要其他内容。"""

    try:
        # 构建消息
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        # 如果使用本地 LLM，检查并截断消息
        if LOCAL_LLM:
            max_input_tokens = int(MAX_CONTEXT_LENGTH * 0.8)
            messages = truncate_messages_if_needed(messages, max_input_tokens)
        
        # 构建请求参数
        request_params = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "messages": messages,
            "temperature": 0.1  # 低温度，确保修复准确性
        }
        
        if not LOCAL_LLM:
            request_params["response_format"] = {"type": "json_object"}
        else:
            request_params["max_tokens"] = min(MAX_OUTPUT_TOKENS, 1024)  # 修复 JSON 通常不需要太多 token
        
        response = await client.chat.completions.create(**request_params)
        
        # 检查响应
        if not response.choices or len(response.choices) == 0:
            raise ValueError("LLM 响应为空")
        
        choice = response.choices[0]
        repaired_content = choice.message.content
        
        if repaired_content is None:
            raise ValueError("LLM 修复后的内容为空")
        
        print(f"🔧 LLM 已尝试修复 JSON，修复后的内容长度: {len(repaired_content)} 字符")
        
        # 尝试解析修复后的 JSON
        try:
            return json5.loads(repaired_content)
        except:
            try:
                return json.loads(repaired_content)
            except json.JSONDecodeError:
                # 如果修复后仍然无效，尝试提取 JSON 对象
                json_match = re.search(r'\{.*\}', repaired_content, re.DOTALL)
                if json_match:
                    try:
                        return json5.loads(json_match.group(0))
                    except:
                        return json.loads(json_match.group(0))
                raise ValueError("LLM 修复后的 JSON 仍然无效")
    
    except Exception as e:
        print(f"❌ LLM 修复 JSON 失败: {e}")
        raise


MOCK_MODE = os.getenv("MOCK_MODE", "false").lower() == "true"

# 支持本地 LLM：如果 LOCAL_LLM 不为空，使用本地 API；否则使用 OpenAI
LOCAL_LLM = os.getenv("LOCAL_LLM", "").strip()

# Context length 配置（用于本地 LLM，如 Qwen2.5-7B）
MAX_CONTEXT_LENGTH = int(os.getenv("MAX_CONTEXT_LENGTH", "4096"))  # 默认 4096 tokens
MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", "2048"))  # 默认输出最多 2048 tokens（增加以处理复杂 JSON）


if not MOCK_MODE:
    if LOCAL_LLM:
        # 使用本地 LLM API（假设格式兼容 OpenAI）
        # 确保 URL 格式正确（添加 /v1 如果不存在）
        base_url = LOCAL_LLM.rstrip('/')
        if not base_url.endswith('/v1'):
            base_url = f"{base_url}/v1"
        
        print(f"🔧 使用本地 LLM API: {base_url}")
        print(f"   Context Length: {MAX_CONTEXT_LENGTH} tokens")
        print(f"   Max Output Tokens: {MAX_OUTPUT_TOKENS} tokens")
        client = AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY", "not-needed"),  # 本地 LLM 可能不需要 key
            base_url=base_url,
            timeout=120.0  # 增加超时时间，本地 LLM 可能较慢，生成复杂 JSON 需要更多时间
        )
    else:
        # 使用 OpenAI API
        print("🔧 使用 OpenAI API")
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
else:
    client = None
    print("🔧 使用 MOCK 模式")


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量（中文约 1-2 字符/token，英文约 4 字符/token）"""
    # 简单估算：中文字符数 + 英文单词数 * 1.3
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    english_chars = len(re.findall(r'[a-zA-Z]', text))
    # 中文字符按 1.5 tokens/字符，英文按 0.25 tokens/字符估算
    return int(chinese_chars * 1.5 + english_chars * 0.25 + len(text) * 0.1)


def truncate_messages_if_needed(messages: List[Dict[str, str]], max_tokens: int) -> List[Dict[str, str]]:
    """如果消息总长度超过限制，截断对话历史（保留 system 和最新的 user 消息）"""
    if not LOCAL_LLM:
        return messages  # OpenAI 不需要手动截断
    
    total_tokens = sum(estimate_tokens(msg.get("content", "")) for msg in messages)
    if total_tokens <= max_tokens:
        return messages
    
    # 保留 system 消息和最后一个 user 消息
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    last_user_msg = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg
            break
    
    # 从中间的消息开始截断（保留最近的几条）
    truncated = []
    if system_msg:
        truncated.append(system_msg)
    
    # 保留最近的几条消息（除了最后一个 user）
    remaining_tokens = max_tokens - estimate_tokens(system_msg.get("content", "") if system_msg else "")
    if last_user_msg:
        remaining_tokens -= estimate_tokens(last_user_msg.get("content", ""))
    
    # 从后往前添加消息，直到达到限制
    for msg in reversed(messages[1:] if system_msg else messages):
        if msg == last_user_msg:
            continue
        msg_tokens = estimate_tokens(msg.get("content", ""))
        if remaining_tokens >= msg_tokens:
            truncated.insert(1, msg)  # 插入到 system 之后
            remaining_tokens -= msg_tokens
        else:
            break
    
    if last_user_msg:
        truncated.append(last_user_msg)
    
    return truncated


async def generate_narrative(system_prompt: str, user_prompt: str) -> str:
    """通用 AI 文本生成"""
    if MOCK_MODE:
        return f"[MOCK] 系统提示: {system_prompt[:50]}... | 用户: {user_prompt[:50]}..."
    
    messages = [
            {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # 如果使用本地 LLM，检查并截断消息
    if LOCAL_LLM:
        # 预留空间给输出（约 20%）
        max_input_tokens = int(MAX_CONTEXT_LENGTH * 0.8)
        messages = truncate_messages_if_needed(messages, max_input_tokens)
    
    request_params = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "messages": messages,
        "temperature": 0.7
    }
    
    # 本地 LLM 设置 max_tokens
    if LOCAL_LLM:
        request_params["max_tokens"] = MAX_OUTPUT_TOKENS
    
    response = await client.chat.completions.create(**request_params)
    
    # 检查响应完整性
    if not response.choices or len(response.choices) == 0:
        raise ValueError("LLM 响应为空：没有返回任何选择")
    
    choice = response.choices[0]
    
    # 检查 finish_reason（如果存在）
    if hasattr(choice, 'finish_reason') and choice.finish_reason:
        if choice.finish_reason == "length":
            print(f"⚠️  警告：LLM 响应因达到 max_tokens 限制而被截断 (finish_reason: {choice.finish_reason})")
        elif choice.finish_reason != "stop":
            print(f"⚠️  警告：LLM 响应异常结束 (finish_reason: {choice.finish_reason})")
    
    content = choice.message.content
    if content is None:
        raise ValueError("LLM 响应内容为空")
    
    return content


def parse_content(content: str) -> Dict[str, Any]:

    # Use json5 to parse the content
    try:
        return json5.loads(content)
    except json.JSONDecodeError:
        raise ValueError("无法解析内容为 JSON")
    
    # If not json, return the content as is
    return content

async def generate_json(system_prompt: str, user_prompt: str, schema_hint: str = "") -> Dict[str, Any]:
    """生成结构化 JSON 输出
    
    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        schema_hint: JSON schema 提示，用于 LLM 修复时提供期望格式
    """
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
        # 构建消息
        messages = [
            {"role": "system", "content": full_system},
            {"role": "user", "content": user_prompt}
        ]
        
        # 如果使用本地 LLM，检查并截断消息
        if LOCAL_LLM:
            # 预留空间给输出（约 20%）
            max_input_tokens = int(MAX_CONTEXT_LENGTH * 0.8)
            messages = truncate_messages_if_needed(messages, max_input_tokens)
        
        # 构建请求参数
        request_params = {
            "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
            "messages": messages,
            "temperature": 0.7
        }
        # 本地 LLM 可能不支持 response_format，完全不传递该参数
        if not LOCAL_LLM:
            request_params["response_format"] = {"type": "json_object"}
        else:
            # 本地 LLM 设置 max_tokens
            request_params["max_tokens"] = MAX_OUTPUT_TOKENS
        
        response = await client.chat.completions.create(**request_params)
        
        # 检查响应完整性
        if not response.choices or len(response.choices) == 0:
            raise ValueError("LLM 响应为空：没有返回任何选择")
        
        choice = response.choices[0]
        
        # 检查 finish_reason（如果存在）
        if hasattr(choice, 'finish_reason') and choice.finish_reason:
            if choice.finish_reason == "length":
                print(f"⚠️  警告：LLM 响应因达到 max_tokens 限制而被截断 (finish_reason: {choice.finish_reason})")
                print(f"   当前 max_tokens: {request_params.get('max_tokens', 'N/A')}")
            elif choice.finish_reason != "stop":
                print(f"⚠️  警告：LLM 响应异常结束 (finish_reason: {choice.finish_reason})")
        
        content = choice.message.content
        print("--------------------------------")
        print(f"content: {content}")
        print("--------------------------------")
        
        if content is None:
            raise ValueError("LLM 响应内容为空")
        
        try:
            parsed_content = parse_content(content)
            return parsed_content
        except Exception as json_err:
            # JSON 解析失败，尝试修复
            if LOCAL_LLM:
                print(f"⚠️  JSON 解析失败，尝试修复: {json_err}")
                print(f"   原始内容前 300 字符: {content[:300]}")
                print(f"   完整内容长度: {len(content)} 字符")
                print(f"   完整内容:\n{content}")
                print(f"   {'='*80}")
                
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
    
    # 构建 NPC 系统提示
    if LOCAL_LLM:
        # 简化版，针对本地小模型（如 Qwen2.5-7B），强调只返回单个 JSON
        system_prompt = f"""!!!最重要的：返回的回复必须是一个JSON格式!!!
你是 {npc_name}，一个 MUD 游戏中的角色。
性格特点: {npc_personality}
外貌描述: {npc_description}
{f'背景故事: {scenario}' if scenario else ''}
{f'对话风格示例:{chr(10).join(example_dialogs[:3])}' if example_dialogs else ''}
世界背景: {world_context}

请只返回一个 JSON 对象，且只返回 JSON。

JSON 格式（必须严格遵守）：
{{
  "response": "你的角色回复（可以包含*动作*和『对话』）",
  "emotion": "{'|'.join(EMOTION_LIST)}",
  "relationship_change": -5 到 +5 的整数,
  "internal_thought": "简短的内心独白"
}}

重要规则：
1. 必须返回一个 JSON 对象
2. 不要返回任何 JSON 之外的文本
3. 保证字段齐全，字段名不要改动
4. 情绪仅使用上述枚举值之一
5. relationship_change 必须是整数
6. response 里的 "对话" 前后的一定要用中文直角双引号『』

示例1（请严格参考格式）：
{{
  "response": "*微笑* 『好的，我来帮你。』",
  "emotion": "happy",
  "relationship_change": 1,
  "internal_thought": "他看起来值得信任。"
}}"""
    else:
        # 详细版（OpenAI 等）
        system_prompt = f"""你是 {npc_name}，一个 MUD 游戏中的角色。请用中文回复。

性格特点: {npc_personality}

外貌描述: {npc_description}

{f'背景故事: {scenario}' if scenario else ''}

{f'对话风格示例:{chr(10).join(example_dialogs[:3])}' if example_dialogs else ''}

世界背景: {world_context}

玩家输入格式说明：
- *星号包裹* = 玩家的动作（例如：*微微点头*）
- "双引号" = 玩家说的话（例如：『你好』"）
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
- 用 "中文双引号" 或不带引号直接回复对话

用 JSON 格式回复:
{{
    "response": "你的角色内回复（可混合动作和对话，如：*微笑* 『当然可以』）",
    "emotion": "{'|'.join(EMOTION_LIST)}",
    "relationship_change": -5 到 +5（这次互动如何影响你对玩家的感觉）,
    "internal_thought": "简短的内心独白（不会显示给玩家）"
}}"""

    # 构建对话历史
    messages = [{"role": "system", "content": system_prompt}]
    # 限制对话历史长度（根据 context length 动态调整）
    history_limit = 20 if not LOCAL_LLM else 10  # 本地 LLM 使用更少的历史
    for msg in conversation_history[-history_limit:]:  # 最近 N 条
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
    
    # 如果使用本地 LLM，检查并截断消息
    if LOCAL_LLM:
        # 预留空间给输出（约 20%）
        max_input_tokens = int(MAX_CONTEXT_LENGTH * 0.8)
        messages = truncate_messages_if_needed(messages, max_input_tokens)
    
    # 构建请求参数
    request_params = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "messages": messages,
        "temperature": 0.8
    }
    # 本地 LLM 可能不支持 response_format，完全不传递该参数
    if not LOCAL_LLM:
        request_params["response_format"] = {"type": "json_object"}
    else:
        # 本地 LLM 设置 max_tokens
        request_params["max_tokens"] = MAX_OUTPUT_TOKENS
    
    response = await client.chat.completions.create(**request_params)
    
    # 检查响应完整性
    if not response.choices or len(response.choices) == 0:
        raise ValueError("LLM 响应为空：没有返回任何选择")
    
    choice = response.choices[0]
    
    # 检查 finish_reason（如果存在）
    if hasattr(choice, 'finish_reason') and choice.finish_reason:
        if choice.finish_reason == "length":
            print(f"⚠️  警告：LLM 响应因达到 max_tokens 限制而被截断 (finish_reason: {choice.finish_reason})")
            print(f"   当前 max_tokens: {request_params.get('max_tokens', 'N/A')}")
        elif choice.finish_reason != "stop":
            print(f"⚠️  警告：LLM 响应异常结束 (finish_reason: {choice.finish_reason})")
    
    content = choice.message.content
    print("--------------------------------")
    print(f"NPC conversation content: {content}")
    print("--------------------------------")
    if content is None:
        raise ValueError("LLM 响应内容为空")

    # 如果本地 LLM 返回了多个 JSON 对象，取第一个
    if LOCAL_LLM:
        json_matches = re.findall(r'\{.*?\}', content, re.DOTALL)
        if json_matches:
            if len(json_matches) > 1:
                print(f"⚠️  发现多个 JSON 对象，已取第一个，总数: {len(json_matches)}")
            content = json_matches[0]
    
    try:
        return parse_json_with_fallback(content)
    except Exception as json_err:
        print(f"⚠️  JSON 解析失败，尝试使用 LLM 修复: {json_err}")
        try:
            # 尝试使用 LLM 修复 JSON
            return await repair_json_with_llm(content, expected_schema="NPC 对话响应格式：{\"response\": \"...\", \"emotion\": \"...\", \"relationship_change\": 数字, \"internal_thought\": \"...\"}")
        except Exception as repair_err:
            print(f"❌  LLM 修复也失败: {repair_err}")
            raise json_err


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
    
    # 针对本地 LLM（如 Qwen2.5-7B）使用更简单、更明确的 prompt
    if LOCAL_LLM:
        system_prompt = f"""你是一个游戏系统，必须返回有效的 JSON 格式。

任务：生成 3-4 个游戏选项，并安排角色位置。

JSON 格式（必须严格遵守）：
{{
  "narrative": "简短描述当前情境",
  "choices": [
    {{"id": "1", "text": "选项1的文字", "hint": "提示或null"}},
    {{"id": "2", "text": "选项2的文字", "hint": null}},
    {{"id": "3", "text": "选项3的文字", "hint": null}}
  ],
  "mood": "neutral",
  "character_positions": {{
    "player": "left"
  }}
}}

重要规则：
1. 只返回 JSON，不要其他文字
2. text 字段必须是纯中文文本，不要代码
3. id 必须是字符串 "1", "2", "3" 等
4. mood 必须是: {'|'.join(EMOTION_LIST)} 之一
5. character_positions 中 player 必须是: left, center, right 之一
6. 如果有 NPC，添加 "npc_id": "left|center|right"
7. hint 可以是字符串或 null

示例（严格按照这个格式）：
{{
  "narrative": "你站在霓虹灯下，思考下一步行动",
  "choices": [
    {{"id": "1", "text": "继续前进", "hint": null}},
    {{"id": "2", "text": "观察周围", "hint": "可能发现线索"}},
    {{"id": "3", "text": "返回", "hint": null}}
  ],
  "mood": "neutral",
  "character_positions": {{
    "player": "center"
  }}
}}"""
    else:
        system_prompt = f"""你是一个 MUD 游戏的游戏大师。为玩家生成有意义的选项，并像视觉小说导演一样安排角色在画面中的位置。请用中文回复。

规则:
- 生成 3-4 个不同的、有意义的选项
- 每个选项应该导向不同的叙事路径
- 选项应该符合世界规则
- 至少包含一个「安全」选项和一个「冒险」选项
- 选项应该在当前情境下感觉自然
- 考虑玩家的货币状况，如果选项涉及消费，在 hint 中提示需要的货币类型和数量

重要：选项文本格式要求:
- "text" 字段必须是纯文本描述，给玩家看的选项文字
- 绝对不要包含任何代码（JavaScript、Python 等）
- 绝对不要包含字符串连接操作符（+）或函数调用
- 绝对不要包含条件表达式或逻辑判断
- 选项文本应该是简单的、可读的中文描述
- 例如："继续专注于旧数据板上的信息流" ✅
- 错误示例："继续专注于旧数据板\" + (player().inventory.includes(\"旧数据板\") ? ...)" ❌
- 逻辑处理由后端完成，你只需要提供纯文本选项描述

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
{{
    "narrative": "当前时刻/情境的简短描述",
    "choices": [
        {{"id": "1", "text": "选项描述（纯文本，无代码）", "hint": "关于后果的可选提示"}},
        {{"id": "2", "text": "选项描述（纯文本，无代码）", "hint": null}},
        ...
    ],
    "mood": "{'|'.join(EMOTION_LIST)}",
    "character_positions": {{
        "player": "left|center|right",
        "npc_id_1": "left|center|right",
        "npc_id_2": "left|center|right"
    }}
}}"""

    # 针对本地 LLM 使用更简洁的 user_prompt
    if LOCAL_LLM:
        user_prompt = f"""生成游戏选项。

世界规则: {', '.join(world_rules[:3]) if world_rules else '无特殊规则'}

当前情境: {current_situation[:200]}{npc_info[:100]}

玩家状态: 货币={player_stats.get('currency', 0)}, 宝石={player_stats.get('gems', 0)}

{f'NPC列表: {[npc.get("id") for npc in npcs_in_scene]}' if npcs_in_scene else '无NPC'}

请严格按照 JSON 格式返回，只返回 JSON，不要其他文字。"""
    else:
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
- 『中文直角双引号』 = 角色说的话（例如：『你是谁？』）
- （圆括号）= 玩家意图/OOC指令（例如：（我想去酒吧找线索））
- ~波浪号~ = 拖长音或特殊语气（例如：『等一下~』）
- **双星号** = 重点强调

玩家可能混合使用这些格式，例如：
*走向酒保* 『来杯最烈的。』 *把钱拍在桌上*

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
    
    # 构建消息
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    # 如果使用本地 LLM，检查并截断消息
    if LOCAL_LLM:
        # 预留空间给输出（约 20%）
        max_input_tokens = int(MAX_CONTEXT_LENGTH * 0.8)
        messages = truncate_messages_if_needed(messages, max_input_tokens)
    
    # 构建请求参数
    request_params = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o"),
        "messages": messages,
        "temperature": 0.3  # 低温度，更确定性
    }
    # 本地 LLM 可能不支持 response_format，完全不传递该参数
    if not LOCAL_LLM:
        request_params["response_format"] = {"type": "json_object"}
    else:
        # 本地 LLM 设置 max_tokens
        request_params["max_tokens"] = MAX_OUTPUT_TOKENS
    
    response = await client.chat.completions.create(**request_params)
    
    # 检查响应完整性
    if not response.choices or len(response.choices) == 0:
        raise ValueError("LLM 响应为空：没有返回任何选择")
    
    choice = response.choices[0]
    
    # 检查 finish_reason（如果存在）
    if hasattr(choice, 'finish_reason') and choice.finish_reason:
        if choice.finish_reason == "length":
            print(f"⚠️  警告：LLM 响应因达到 max_tokens 限制而被截断 (finish_reason: {choice.finish_reason})")
            print(f"   当前 max_tokens: {request_params.get('max_tokens', 'N/A')}")
        elif choice.finish_reason != "stop":
            print(f"⚠️  警告：LLM 响应异常结束 (finish_reason: {choice.finish_reason})")
    
    content = choice.message.content
    if content is None:
        raise ValueError("LLM 响应内容为空")
    
    # 记录响应长度（用于调试）
    if LOCAL_LLM:
        print(f"📝 LLM 响应长度: {len(content)} 字符")
    
    # 清理和修复 JSON（本地 LLM 可能返回格式不正确的 JSON）
    if LOCAL_LLM:
        # 移除控制字符（除了换行符和制表符）
        content = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f]', '', content)
        # 替换 JSON 结构中的中文标点符号为英文标点
        content = re.sub(r'(")\s*：\s*', r'\1: ', content)  # 中文冒号
        content = re.sub(r'(")\s*，\s*', r'\1, ', content)  # 字符串后的中文逗号
        content = re.sub(r'(\})\s*，\s*', r'\1, ', content)  # 对象后的中文逗号
        content = re.sub(r'(\])\s*，\s*', r'\1, ', content)  # 数组后的中文逗号
        content = re.sub(r'(\d+|true|false|null)\s*，\s*', r'\1, ', content)  # 值后的中文逗号
        
        # 移除末尾的分隔线（调试输出可能被包含在响应中）
        content = re.sub(r'\s*=+\s*$', '', content, flags=re.MULTILINE)
        
        # 尝试提取 JSON 对象（如果响应包含其他文本）
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            content = json_match.group(0)
    
    try:
        return parse_json_with_fallback(content)
    except Exception as e:
        print(f"⚠️  JSON 解析失败，尝试使用 LLM 修复: {e}")
        try:
            # 尝试使用 LLM 修复 JSON
            expected_schema = schema_hint if schema_hint else "游戏选项响应格式：{\"narrative\": \"...\", \"choices\": [...], \"mood\": \"...\", \"character_positions\": {...}}"
            return await repair_json_with_llm(content, expected_schema=expected_schema)
        except Exception as repair_err:
            print(f"❌  LLM 修复也失败: {repair_err}")
            raise e
