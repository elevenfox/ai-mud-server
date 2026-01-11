"""Seed script to initialize a demo world - 中文版"""

import asyncio
import os
from app.models.schemas import World, Location, NPC, Player
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
            current_mood="mysterious"
        )
        session.add(world)
        
        # 2. 创建地点
        loc1 = Location(
            id="loc_1",
            world_id="world_1",
            name="霓虹小巷",
            description="一条潮湿狭窄的小巷，闪烁的霓虹灯照亮四周。空气中弥漫着合成拉面的香味。蒸汽从地面的格栅中升起，远处悬浮车的轰鸣声在头顶回荡。",
            background_url="/static/worlds/world_1/backgrounds/neon_alley.png",
            connections=["loc_2", "loc_3"]
        )
        loc2 = Location(
            id="loc_2",
            world_id="world_1",
            name="故障酒吧",
            description="一家高科技地下酒吧，黑客和混混们聚集在此。全息舞者在小舞台上闪烁。合成波音乐的重低音在你胸腔中震动。空气中弥漫着电子烟雾和低语的交易声。",
            background_url="/static/worlds/world_1/backgrounds/glitch_bar.png",
            connections=["loc_1"]
        )
        loc3 = Location(
            id="loc_3",
            world_id="world_1",
            name="黑市集",
            description="一个混乱的露天市场，从非法植入体到异域美食应有尽有。摊贩们互相叫喊，无人机在摊位间穿梭，人群如同一个活着的有机体般流动。",
            background_url="/static/worlds/world_1/backgrounds/market.png",
            connections=["loc_1", "loc_4"]
        )
        loc4 = Location(
            id="loc_4",
            world_id="world_1",
            name="废弃仓库",
            description="一座位于区域边缘的破败建筑。涂鸦覆盖着墙壁，唯一的光线来自天花板的裂缝。阴影中有什么东西在移动。",
            background_url="/static/worlds/world_1/backgrounds/warehouse.png",
            connections=["loc_3"]
        )
        session.add_all([loc1, loc2, loc3, loc4])
        
        # 3. 创建 NPC
        npc1 = NPC(
            id="npc_1",
            world_id="world_1",
            name="凯尔",
            description="一个愤世嫉俗的情报贩子，带着一只发着淡蓝光芒的义眼。他的脸庞饱经风霜，但目光锐利。",
            personality="讽刺、博学、警惕。说话简短。不信任任何人，但尊重有能力的人。对老地球爵士乐有一种软肋。",
            location_id="loc_2",
            portrait_url="/static/worlds/world_1/npcs/npc_1/default.png",
            first_message="*角落卡座里的一个身影在你靠近时抬起头。他的义眼嗡嗡作响，对准了你。* 又一个迷途的灵魂来找答案？坐吧。但记住——我卖的东西可不便宜。",
            scenario="凯尔五年前失去了搭档，死于企业刺客之手。现在他靠贩卖情报为生，总是领先那些想让他闭嘴的人一步。",
            example_dialogs=[
                "用户: 你能告诉我关于那个企业的事吗？\n凯尔: *往后靠* 哪个？都一样。穿西装的鲨鱼。但如果你说的是联合公司…… *他的眼睛闪烁* ……那可是危险地带。",
                "用户: 我需要你的帮助。\n凯尔: *冷笑* 谁不是呢。问题是，你能给我什么作为交换？"
            ],
            current_emotion="default",
            relationship=0
        )
        
        npc2 = NPC(
            id="npc_2",
            world_id="world_1",
            name="米拉",
            description="一个年轻的街头摊贩，留着亮粉色的头发和强化机械臂。她带着开朗的笑容卖着「回收」科技产品。",
            personality="乐观、健谈、街头智慧。用活泼的外表掩盖敏锐的商业头脑。对帮助过她的人非常忠诚。",
            location_id="loc_3",
            portrait_url="/static/worlds/world_1/npcs/npc_2/default.png",
            first_message="*一个年轻女子从杂乱的摊位后热情地挥手* 嘿嘿！市场来新面孔啦！在找什么特别的东西？我这有全区最好的「二手」科技！",
            scenario="米拉在这些街道上长大。她的强化机械臂是一位神秘恩人送的礼物，那人救过她的命。她一直在寻找关于自己过去的答案。",
            example_dialogs=[
                "用户: 你在卖什么？\n米拉: *骄傲地比划* 只有最精品的回收科技！神经接口、全息投影仪、安保破解器…… *眨眼* 当然全都是合法的。",
            ],
            current_emotion="happy",
            relationship=0
        )
        
        npc3 = NPC(
            id="npc_3",
            world_id="world_1",
            name="幽灵",
            description="一个苍白的身影，裹着深色衣物，脸被不断变换图案的全息面具遮住。",
            personality="神秘、耐心、观察入微。说话喜欢打哑谜。似乎知道的比他们应该知道的要多。既不友好也不敌意。",
            location_id="loc_4",
            portrait_url="/static/worlds/world_1/npcs/npc_3/default.png",
            first_message="*一个影子从墙上脱离。一个声音响起，既非男性也非女性* 小巷来了新访客。真是……有趣。你是顺着线找到我的？还是线找到了你？",
            scenario="没人知道幽灵的真实身份或来历。他们在需要时出现，给出神秘的指引，然后消失。有人说他们是AI。有人说是更奇怪的东西。",
            example_dialogs=[
                "用户: 你是谁？\n幽灵: *面具变成一个问号* 谁是谁呢？名字是牢笼。我是……一个催化剂。"
            ],
            current_emotion="default",
            relationship=0
        )
        session.add_all([npc1, npc2, npc3])
        
        # 4. 创建玩家
        player = Player(
            id="player_1",
            world_id="world_1",
            name="新手",
            location_id="loc_1",
            inventory=["旧数据板", "50信用点"]
        )
        session.add(player)
        
        await session.commit()
        print("✅ 数据库初始化成功！")
        print("   世界: 霓虹城")
        print("   地点: 4 个")
        print("   NPC: 3 个 (凯尔、米拉、幽灵)")
        print("   玩家: 新手 @ 霓虹小巷")
    
    # 关闭数据库引擎连接
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(seed())
    finally:
        os._exit(0)  # 强制退出，避免挂起
