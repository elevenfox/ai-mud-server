"""Seed script to initialize a demo world - 中文版"""

import asyncio
import os
import uuid
from pathlib import Path
from app.models.schemas import (
    World, Location, NPC, Player,
    LocationTemplate, CharacterTemplate
)
from app.db.session import engine, init_db
from sqlmodel.ext.asyncio.session import AsyncSession


async def seed():
    await init_db()
    async with AsyncSession(engine) as session:
        # 1. 创建世界
        world = World(
            id="world_1",
            time=0,
            seed=12345,
            name="霓虹城",
            description="一座赛博朋克风格的都市，霓虹灯永不熄灭，每个角落都藏着秘密。",
            rules=[
                "科技发达但不稳定",
                "企业财团控制着大部分资源",
                "暴力行为会有后果 - 当局会介入调查",
                "信任是稀缺品，必须赢得",
                "信息是最有价值的货币"
            ],
            flags={"intro_complete": False, "met_kael": False},
            current_mood="mysterious",
            # 经济系统配置
            currency_name="信用点",
            gem_name="宝石",
            currency_rules="信用点用于购买游戏内的物品、服务、食物、装备、情报等。宝石用于购买不影响游戏平衡的装饰性道具，如角色皮肤、配饰、特效等。"
        )
        session.add(world)
        await session.flush()  # 确保 world 有 ID
        
        # 2. 创建场景模板和地点
        # 定义场景数据
        locations_data = [
            {
                "id": "loc_1",
                "name": "霓虹小巷",
                "description": "一条潮湿狭窄的小巷，闪烁的霓虹灯照亮四周。空气中弥漫着合成拉面的香味。蒸汽从地面的格栅中升起，远处悬浮车的轰鸣声在头顶回荡。",
                "is_starting": True,
                "connections": ["loc_2", "loc_3"]
            },
            {
                "id": "loc_2",
                "name": "故障酒吧",
                "description": "一家高科技地下酒吧，黑客和混混们聚集在此。全息舞者在小舞台上闪烁。合成波音乐的重低音在你胸腔中震动。空气中弥漫着电子烟雾和低语的交易声。",
                "is_starting": False,
                "connections": ["loc_1"]
            },
            {
                "id": "loc_3",
                "name": "黑市集",
                "description": "一个混乱的露天市场，从非法植入体到异域美食应有尽有。摊贩们互相叫喊，无人机在摊位间穿梭，人群如同一个活着的有机体般流动。",
                "is_starting": False,
                "connections": ["loc_1", "loc_4"]
            },
            {
                "id": "loc_4",
                "name": "废弃仓库",
                "description": "一座位于区域边缘的破败建筑。涂鸦覆盖着墙壁，唯一的光线来自天花板的裂缝。阴影中有什么东西在移动。",
                "is_starting": False,
                "connections": ["loc_3"]
            }
        ]
        
        locations = []
        location_templates = []
        
        for loc_data in locations_data:
            # 创建 LocationTemplate
            loc_template_id = f"loc_template_{loc_data['id']}"
            loc_template = LocationTemplate(
                id=loc_template_id,
                name=loc_data["name"],
                description=loc_data["description"],
                tags=["赛博朋克", "霓虹城"],
                is_starting_location=loc_data["is_starting"],
                default_connections=loc_data["connections"]
            )
            location_templates.append(loc_template)
            session.add(loc_template)
            
            # 背景图片路径（可在 admin UI 中生成）
            background_path = f"/static/worlds/world_1/backgrounds/{loc_data['id']}.png"
            
            # 创建 Location（游戏运行时）
            location = Location(
                id=loc_data["id"],
                world_id="world_1",
                name=loc_data["name"],
                description=loc_data["description"],
                background_url=background_path or f"/static/worlds/world_1/backgrounds/{loc_data['id']}.png",
                connections=loc_data["connections"],
                is_starting_location=loc_data["is_starting"]
            )
            locations.append(location)
            session.add(location)
        
        await session.flush()
        
        # 3. 创建角色模板和 NPC
        # 定义 NPC 数据
        npcs_data = [
            {
                "id": "npc_1",
                "name": "凯尔",
                "description": "一个愤世嫉俗的情报贩子，带着一只发着淡蓝光芒的义眼。他的脸庞饱经风霜，但目光锐利。",
                "personality": "讽刺、博学、警惕。说话简短。不信任任何人，但尊重有能力的人。对老地球爵士乐有一种软肋。",
                "location_id": "loc_2",
                "first_message": "*角落卡座里的一个身影在你靠近时抬起头。他的义眼嗡嗡作响，对准了你。* 又一个迷途的灵魂来找答案？坐吧。但记住——我卖的东西可不便宜。",
                "scenario": "凯尔五年前失去了搭档，死于企业刺客之手。现在他靠贩卖情报为生，总是领先那些想让他闭嘴的人一步。",
                "example_dialogs": [
                    "用户: 你能告诉我关于那个企业的事吗？\n凯尔: *往后靠* 哪个？都一样。穿西装的鲨鱼。但如果你说的是联合公司…… *他的眼睛闪烁* ……那可是危险地带。",
                    "用户: 我需要你的帮助。\n凯尔: *冷笑* 谁不是呢。问题是，你能给我什么作为交换？"
                ],
                "gender": "male",
                "age": 45,
                "occupation": "情报贩子"
            },
            {
                "id": "npc_2",
                "name": "米拉",
                "description": "一个年轻的街头摊贩，留着亮粉色的头发和强化机械臂。她带着开朗的笑容卖着「回收」科技产品。",
                "personality": "乐观、健谈、街头智慧。用活泼的外表掩盖敏锐的商业头脑。对帮助过她的人非常忠诚。",
                "location_id": "loc_3",
                "first_message": "*一个年轻女子从杂乱的摊位后热情地挥手* 嘿嘿！市场来新面孔啦！在找什么特别的东西？我这有全区最好的「二手」科技！",
                "scenario": "米拉在这些街道上长大。她的强化机械臂是一位神秘恩人送的礼物，那人救过她的命。她一直在寻找关于自己过去的答案。",
                "example_dialogs": [
                    "用户: 你在卖什么？\n米拉: *骄傲地比划* 只有最精品的回收科技！神经接口、全息投影仪、安保破解器…… *眨眼* 当然全都是合法的。",
                ],
                "gender": "female",
                "age": 22,
                "occupation": "摊贩"
            },
            {
                "id": "npc_3",
                "name": "幽灵",
                "description": "一个苍白的身影，裹着深色衣物，脸被不断变换图案的全息面具遮住。",
                "personality": "神秘、耐心、观察入微。说话喜欢打哑谜。似乎知道的比他们应该知道的要多。既不友好也不敌意。",
                "location_id": "loc_4",
                "first_message": "*一个影子从墙上脱离。一个声音响起，既非男性也非女性* 小巷来了新访客。真是……有趣。你是顺着线找到我的？还是线找到了你？",
                "scenario": "没人知道幽灵的真实身份或来历。他们在需要时出现，给出神秘的指引，然后消失。有人说他们是AI。有人说是更奇怪的东西。",
                "example_dialogs": [
                    "用户: 你是谁？\n幽灵: *面具变成一个问号* 谁是谁呢？名字是牢笼。我是……一个催化剂。"
                ],
                "gender": "unknown",
                "age": None,
                "occupation": "神秘存在"
            }
        ]
        
        npcs = []
        character_templates = []
        
        for npc_data in npcs_data:
            # 创建 CharacterTemplate
            char_template_id = f"char_template_{npc_data['id']}"
            char_template = CharacterTemplate(
                id=char_template_id,
                name=npc_data["name"],
                description=npc_data["description"],
                personality=npc_data["personality"],
                first_message=npc_data["first_message"],
                scenario=npc_data["scenario"],
                example_dialogs=npc_data["example_dialogs"],
                tags=["NPC", "赛博朋克"],
                gender=npc_data.get("gender"),
                age=npc_data.get("age"),
                occupation=npc_data.get("occupation"),
                is_player_avatar=False
            )
            character_templates.append(char_template)
            session.add(char_template)
            
            # 立绘路径（可在 admin UI 中生成）
            portrait_path = f"/static/worlds/world_1/npcs/{npc_data['id']}/default.png"
            
            # 创建 NPC（游戏运行时）
            npc = NPC(
                id=npc_data["id"],
                world_id="world_1",
                location_id=npc_data["location_id"],
                template_id=char_template_id,  # 关联到模板
                current_emotion="default",
                relationship=0,
                position="center"
            )
            npcs.append(npc)
            session.add(npc)
        
        await session.flush()
        
        # 4. 创建玩家
        player = Player(
            id="player_1",
            world_id="world_1",
            name="新手",
            location_id="loc_1",
            inventory=["旧数据板"],
            currency=50,  # 初始金钱：50 信用点（约等于 50 顿饭）
            gems=0  # 初始宝石：0（需要付费购买）
        )
        session.add(player)
        
        await session.commit()
        print("✅ 数据库初始化成功！")
        print("   世界: 霓虹城")
        print(f"   场景模板: {len(location_templates)} 个")
        print(f"   地点: {len(locations)} 个")
        print(f"   角色模板: {len(character_templates)} 个")
        npc_names = [npc_data['name'] for npc_data in npcs_data]
        print(f"   NPC: {len(npcs)} 个 ({', '.join(npc_names)})")
        print("   玩家: 新手 @ 霓虹小巷")
    
    # 关闭数据库引擎连接
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    finally:
        os._exit(0)  # 强制退出，避免挂起
