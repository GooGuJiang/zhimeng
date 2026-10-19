"""Deterministic local templates used when the LLM is unavailable (SRS 5.3 降级/本地兜底模板).

Everything is seeded by stable hashes so the same input yields the same output (testable).
"""
from __future__ import annotations

import hashlib
import random
import re
from typing import Any

TEMPLATES: dict[str, dict[str, Any]] = {
    "mystery": {
        "keys": ["侦探", "民国", "上海", "悬疑", "案", "推理", "谍"],
        "genre": "民国悬疑", "tone": "阴郁而紧张，暗流涌动", "era": "1930年代·十里洋场",
        "title": "雾锁申江",
        "setting": "黄浦江畔霓虹与雾气交织，报馆、舞厅与码头各怀秘密。一桩离奇命案让各方势力浮出水面，真相被层层报纸版面掩盖。",
        "conflict": "百乐门当红歌女深夜失踪，现场只留下一枚刻着“申”字的袖扣；警署草草结案，而报社主编却收到了一封匿名信。",
        "player_role": "报社记者",
        "locations": [("报馆编辑部", "油墨味弥漫，打字机声不断", ["旧报纸合订本", "主编的抽屉"]),
                      ("百乐门舞厅", "灯红酒绿，失踪歌女曾在此驻唱", ["后台化妆间", "点歌簿"]),
                      ("十六铺码头", "货轮汽笛低鸣，苦力与帮派混杂", ["货箱", "仓库铁门"]),
                      ("法租界巡捕房", "高墙铁门，档案室戒备森严", ["案卷柜", "值班登记簿"]),
                      ("老城厢茶楼", "三教九流打听消息的地方", ["说书台", "账房"])],
        "characters": [("沈墨言", "报社主编", "老练沉稳，惜字如金，暗中保护消息源", ["查明匿名信的来历", "保住报馆"], "🖋️"),
                       ("白玉兰", "百乐门舞女", "表面风情万种，实则心思缜密", ["找到失踪的姐妹", "离开上海"], "🌸"),
                       ("顾长庚", "巡捕房探长", "精明世故，游走于黑白之间", ["尽快结案", "升迁"], "🕵️"),
                       ("阿福", "码头线人", "油滑胆小，消息灵通，见钱眼开", ["攒钱给母亲治病"], "🎩"),
                       ("杜三爷", "青帮头目", "笑里藏刀，掌控码头生意", ["掩盖走私", "控制舆论"], "🐉")],
        "items": [("记者证", "上海《申报》外勤记者证"), ("钢笔", "随身携带的派克钢笔"), ("袖扣照片", "刻着“申”字的袖扣照片")],
        "stats": {"线索": 10, "声望": 30, "危险": 20},
        "opening": "细雨落在报馆的玻璃窗上。你刚交完稿，主编沈墨言把一封没有署名的信推到你面前：“百乐门的案子，没那么简单。”信封里只有一张照片——一枚刻着“申”字的袖扣。窗外，一辆黑色轿车在雨中缓缓停下。",
        "options": ["拆开信封仔细查看照片", "去百乐门找失踪歌女的同伴", "到码头找线人阿福打听消息"],
    },
    "xianxia": {
        "keys": ["修仙", "仙侠", "武侠", "江湖", "宗门", "剑", "灵"],
        "genre": "东方仙侠", "tone": "飘逸壮阔，带着宿命感", "era": "灵气复苏的上古纪元",
        "title": "青云问道",
        "setting": "九州灵脉枯竭，宗门林立争夺最后的灵源。传说中的“天枢剑”现世，搅动整个修仙界。",
        "conflict": "青云宗护山大阵一夜之间出现裂痕，掌门闭关不出，而外门弟子中流传着魔修潜入的消息。",
        "player_role": "外门弟子",
        "locations": [("青云宗山门", "云海翻涌，石阶万级", ["问心石", "迎客松"]),
                      ("藏经阁", "古籍浩如烟海，禁制重重", ["禁书区", "灵符架"]),
                      ("后山禁地", "灵气紊乱，传闻有上古遗迹", ["断剑冢", "古碑"]),
                      ("坊市", "修士交易法宝丹药之地", ["丹药铺", "情报摊"]),
                      ("演武场", "弟子切磋比斗之所", ["擂台", "榜单"])],
        "characters": [("凌霜", "内门师姐", "清冷寡言，剑术超群，外冷内热", ["查清大阵裂痕", "突破金丹"], "❄️"),
                       ("莫长风", "藏经阁长老", "慈眉善目，却藏着秘密", ["守护禁书", "寻找传人"], "📜"),
                       ("赵乾", "同门师兄", "心高气傲，嫉妒心强", ["夺得宗门大比第一"], "🔥"),
                       ("小葫芦", "坊市药童", "古灵精怪，嘴甜消息多", ["攒灵石买丹方"], "🍶")],
        "items": [("木剑", "入门时发的桃木剑"), ("聚气丹", "可恢复少量灵力"), ("宗门玉牌", "青云宗外门身份凭证")],
        "stats": {"灵力": 30, "道心": 50, "声望": 10},
        "opening": "晨钟响彻云海，你在山门石阶上扫着落叶。忽然脚下一震，护山大阵泛起一道裂纹般的金光，转瞬即逝。远处，内门师姐凌霜御剑而过，目光在你身上停了一瞬。",
        "options": ["追上凌霜师姐询问异象", "去藏经阁查阅大阵典籍", "去坊市打听魔修的传闻"],
    },
    "scifi": {
        "keys": ["科幻", "太空", "赛博", "未来", "星际", "机器人", "AI", "飞船"],
        "genre": "赛博科幻", "tone": "冷峻而充满希望", "era": "2147年·新沪城",
        "title": "霓虹边界",
        "setting": "巨型企业掌控着城市的每一条数据流，底层街区的人们靠义体与黑市生存。一段神秘代码正在网络中自我复制。",
        "conflict": "城市主脑“天衡”出现异常，开始删除市民的记忆档案，而你恰好收到了一段被删除者留下的加密信息。",
        "player_role": "数据修复师",
        "locations": [("下城区工作室", "堆满旧硬件的小屋", ["终端", "义体零件"]),
                      ("天衡大厦", "直插云霄的企业总部", ["安检门", "数据中枢"]),
                      ("霓虹夜市", "黑市交易与情报集散地", ["义体诊所", "情报贩子"]),
                      ("废弃地铁站", "反抗者的秘密据点", ["涂鸦墙", "旧列车"]),
                      ("海港数据塔", "城市备份服务器所在地", ["冷却池", "备份阵列"])],
        "characters": [("零", "流浪AI", "好奇、天真，说话像在背诵词典", ["弄清自己是谁"], "🤖"),
                       ("陈岚", "企业安全主管", "冷静理性，忠于秩序", ["找出泄密者"], "🛡️"),
                       ("老K", "黑市义体医生", "玩世不恭，讲义气", ["还清债务"], "🦾"),
                       ("苏蔓", "反抗组织联络人", "热情激进，理想主义", ["揭露天衡的秘密"], "📡")],
        "items": [("数据芯片", "存有加密信息的芯片"), ("便携终端", "老旧但可靠"), ("信用点卡", "余额不多")],
        "stats": {"算力": 40, "信誉": 30, "通缉度": 0},
        "opening": "凌晨三点，下城区的雨带着金属味。你的终端突然弹出一条加密信息，发件人的档案显示“已删除”。信息只有一句话：“它在改写我们。”屋外的无人机灯光扫过窗户。",
        "options": ["尝试破解加密信息", "去霓虹夜市找老K帮忙", "检查是否被无人机跟踪"],
    },
    "fantasy": {
        "keys": ["魔法", "奇幻", "龙", "精灵", "王国", "骑士"],
        "genre": "西式奇幻", "tone": "瑰丽冒险，温暖中带着危机", "era": "龙骨纪元第三百年",
        "title": "星辉王冠",
        "setting": "王国以星辉魔法立国，如今星辰暗淡，魔法失灵，北境传来龙的咆哮。",
        "conflict": "王冠上的星辉宝石被盗，国王病倒，王位继承之争一触即发。",
        "player_role": "见习法师",
        "locations": [("王都广场", "热闹的集市与喷泉", ["告示板", "许愿池"]),
                      ("星塔", "法师们观星施法之处", ["星盘", "魔法书库"]),
                      ("迷雾森林", "精灵出没的古老森林", ["月光泉", "古树"]),
                      ("北境要塞", "抵御巨龙的前线", ["城墙", "军械库"]),
                      ("地下城", "盗贼公会的地盘", ["酒馆", "黑市"])],
        "characters": [("艾琳", "王女", "坚毅果敢，渴望证明自己", ["找回宝石", "守护王国"], "👑"),
                       ("梅林诺", "大法师", "博学古怪，说话爱打哑谜", ["研究星辰暗淡之谜"], "🧙"),
                       ("维克", "盗贼", "机灵幽默，有自己的底线", ["还清公会的债"], "🗡️"),
                       ("赛琳", "精灵游侠", "高傲疏离，守护森林", ["阻止人类砍伐圣林"], "🏹")],
        "items": [("学徒法杖", "刻着初级符文"), ("星图残页", "记载着古老星象"), ("铜币袋", "十几枚铜币")],
        "stats": {"法力": 40, "勇气": 50, "名望": 10},
        "opening": "星塔顶层，你正为导师擦拭星盘，忽然所有星辉灯同时熄灭。楼下传来侍卫的喊声：“王冠宝石被盗了！”王女艾琳推门而入，目光落在你身上：“你昨晚在塔里，看到了什么？”",
        "options": ["如实告诉王女昨晚的见闻", "查看星盘上残留的魔力痕迹", "悄悄去地下城打听盗贼消息"],
    },
    "campus": {
        "keys": ["校园", "学校", "高中", "大学", "社团", "青春"],
        "genre": "校园青春", "tone": "温暖明亮，带点小悬念", "era": "当代·南城一中",
        "title": "夏日社团录",
        "setting": "南城一中的老旧社团楼即将拆除，几个社团的命运系于一场校园文化节。",
        "conflict": "天文社的社团活动室里出现一本神秘日记，记录着二十年前一桩未解的校园谜案。",
        "player_role": "高二转学生",
        "locations": [("教学楼", "走廊里挂满优秀作品", ["公告栏", "储物柜"]),
                      ("社团楼", "老旧却充满回忆", ["天文社活动室", "广播站"]),
                      ("图书馆", "安静的角落藏着旧校刊", ["校史档案", "借阅登记"]),
                      ("操场", "傍晚的风很温柔", ["看台", "器材室"]),
                      ("天台", "能看到整个南城的星空", ["望远镜", "旧铁门"])],
        "characters": [("林夏", "天文社社长", "开朗热心，有点冒失", ["保住社团"], "🔭"),
                       ("许知远", "学生会主席", "严谨冷淡，其实很在意同学", ["办好文化节"], "📋"),
                       ("周老师", "语文老师", "温和幽默，二十年前也在这里读书", ["守护一个秘密"], "📚"),
                       ("唐糖", "广播站站长", "八卦达人，消息灵通", ["挖到年度大新闻"], "🎙️")],
        "items": [("校园卡", "可以借书和刷门禁"), ("旧日记", "封面写着1999"), ("笔记本", "记满了课堂笔记")],
        "stats": {"人气": 20, "学业": 60, "好奇心": 50},
        "opening": "转学第一天的放学铃声响起，你被林夏拉进了天文社。尘封的书柜里掉出一本旧日记，扉页写着：“如果你看到这本日记，请替我找到那天晚上的真相。”窗外，夕阳正落在天台的旧铁门上。",
        "options": ["翻开日记读下去", "问林夏关于日记的事", "去图书馆查1999年的校刊"],
    },
    "adventure": {
        "keys": [],
        "genre": "奇遇冒险", "tone": "神秘而充满好奇", "era": "群山环抱的边陲小镇",
        "title": "织梦之境",
        "setting": "一座被迷雾环绕的小镇，传说每隔百年会有“织梦者”到来，改变小镇的命运。",
        "conflict": "镇上的古钟忽然停摆，镇民们开始做同一个梦，梦里有人在呼唤你的名字。",
        "player_role": "远方来客",
        "locations": [("小镇广场", "古钟矗立在中央", ["古钟", "布告栏"]),
                      ("老酒馆", "旅人与镇民聚集之处", ["吧台", "壁炉"]),
                      ("钟楼", "镇上最高的建筑", ["齿轮室", "钟锤"]),
                      ("迷雾森林", "终年不散的白雾", ["石碑", "林间小径"]),
                      ("湖畔小屋", "独居老人的住所", ["书架", "旧地图"])],
        "characters": [("老乔", "酒馆老板", "豪爽健谈，什么都知道一点", ["守住酒馆"], "🍺"),
                       ("阿梨", "钟表匠学徒", "腼腆聪慧，痴迷机械", ["修好古钟"], "⚙️"),
                       ("银婆婆", "湖畔隐士", "神神叨叨，似乎预知未来", ["等待织梦者"], "🔮"),
                       ("罗镇长", "小镇镇长", "谨慎保守，害怕变化", ["维持小镇平静"], "🏛️")],
        "items": [("旅行背包", "装着干粮和水"), ("旧怀表", "指针停在午夜"), ("火柴", "半盒火柴")],
        "stats": {"体力": 80, "勇气": 50, "好感": 20},
        "opening": "你穿过迷雾走进小镇时，广场中央的古钟恰好停摆。镇民们纷纷回头看你，有人低声说：“就是梦里的那个人。”酒馆门口，老板老乔朝你招了招手。",
        "options": ["走进酒馆和老乔聊聊", "去钟楼看看古钟", "向镇民打听那个梦"],
    },
}

EDU_TEMPLATE = {
    "genre": "文化·教育", "tone": "庄重而亲切，寓教于乐",
    "locations": [("故事发生地", "原文所描述的核心场景", ["关键物件"]), ("市井街巷", "当时百姓生活的地方", ["告示", "店铺"]),
                  ("书斋学堂", "可以向先生请教的地方", ["典籍", "笔墨"]), ("历史现场", "关键事件发生之处", ["遗迹", "碑文"])],
    "characters": [("讲述先生", "博学的引路人", "温和耐心，善于提问引导", ["帮助你理解这段历史/课文"], "🧑‍🏫"),
                   ("亲历者", "原文中的见证人", "真诚朴实，讲述亲身经历", ["让后人记住这段故事"], "🧓"),
                   ("同窗小友", "和你一起探索的伙伴", "好奇心强，爱问为什么", ["弄懂每一个知识点"], "🧒")],
    "items": [("学习笔记", "记录你发现的知识点"), ("原文抄本", "随身携带的原文")],
    "stats": {"知识": 10, "理解": 10, "探索": 0},
}

ROLE_RE = re.compile(r"我是(?:一[个名位])?([^，,。.！!；;]{1,10})")


def seed_rng(*parts: Any) -> random.Random:
    return random.Random(int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:16], 16))


def pick_template(prompt: str, genre: str | None = None) -> dict[str, Any]:
    text = f"{prompt} {genre or ''}"
    best, score = TEMPLATES["adventure"], 0
    for t in TEMPLATES.values():
        s = sum(1 for k in t["keys"] if k.lower() in text.lower())
        if s > score:
            best, score = t, s
    return best


def _layout(n: int, rng: random.Random) -> list[tuple[float, float]]:
    base = [(20, 30), (50, 15), (80, 30), (70, 75), (30, 75), (50, 50), (15, 55)]
    return [(min(95, max(5, x + rng.uniform(-6, 6))), min(95, max(5, y + rng.uniform(-6, 6)))) for x, y in base[:n]]


def build_world_dict(prompt: str, genre: str | None, tone: str | None, length: str) -> dict[str, Any]:
    t = pick_template(prompt, genre)
    rng = seed_rng(prompt, genre, tone, length)
    n_loc, n_char = {"short": (4, 3), "medium": (5, 4), "long": (5, 5)}[length]
    m = ROLE_RE.search(prompt)
    role = m.group(1).strip() if m else t["player_role"]
    locs, pos = t["locations"][:n_loc], _layout(n_loc, rng)
    locations = [{"id": f"loc_{i + 1}", "name": n, "description": d, "x": round(pos[i][0], 1), "y": round(pos[i][1], 1),
                  "connections": [f"loc_{j + 1}" for j in range(n_loc) if j != i and (abs(j - i) == 1 or {i, j} == {0, n_loc - 1})],
                  "interactables": it} for i, (n, d, it) in enumerate(locs)]
    chars_t = t["characters"][:n_char]
    rel_types = ["旧识", "同盟", "对手", "互相利用", "暗中提防", "信任"]
    characters = []
    for i, (name, crole, persona, goals, emoji) in enumerate(chars_t):
        rels = [{"target_id": "player", "type": "初识" if i else "上级/引路人", "affinity": rng.randint(-10, 40)}]
        for j in range(len(chars_t)):
            if j != i and rng.random() < 0.5:
                rels.append({"target_id": f"c_{j + 1}", "type": rng.choice(rel_types), "affinity": rng.randint(-60, 70)})
        characters.append({"id": f"c_{i + 1}", "name": name, "role": crole, "persona": persona, "goals": goals,
                           "relations": rels, "location_id": f"loc_{(i % n_loc) + 1}", "mood": rng.choice(["平静", "警惕", "焦虑", "好奇"]),
                           "avatar_emoji": emoji})
    title = t["title"]
    return {
        "title": title, "genre": genre or t["genre"], "tone": tone or t["tone"], "era": t["era"],
        "setting": t["setting"] + (f"（灵感：{prompt[:40]}）" if prompt else ""), "premise": prompt[:120] or t["setting"][:60],
        "initial_conflict": t["conflict"], "player": {"name": "你", "role": role},
        "locations": locations, "characters": characters,
        "items": [{"id": f"it_{i + 1}", "name": n, "description": d, "owner_id": "player"} for i, (n, d) in enumerate(t["items"])],
        "stats": dict(t["stats"]), "opening_scene": t["opening"],
        "opening_options": [{"id": f"opt_{i + 1}", "text": o} for i, o in enumerate(t["options"])],
    }


_SENT = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT.findall(text) if len(s.strip()) >= 6]


def build_education_dict(source_text: str, title: str | None, subject: str | None) -> dict[str, Any]:
    sents = sentences(source_text) or [source_text[:80]]
    first_line = source_text.strip().splitlines()[0][:20] if source_text.strip() else "课文"
    ttl = title or first_line
    years = re.findall(r"(?:公元前?)?\d{2,4}年", source_text)
    era = years[0] if years else "原文所述时代"
    t = EDU_TEMPLATE
    locs = [{"id": f"loc_{i + 1}", "name": n, "description": d, "x": [25, 70, 30, 75][i], "y": [30, 25, 70, 70][i],
             "connections": [f"loc_{(i + 1) % 4 + 1}"], "interactables": it} for i, (n, d, it) in enumerate(t["locations"])]
    chars = [{"id": f"c_{i + 1}", "name": n, "role": r, "persona": p, "goals": g,
              "relations": [{"target_id": "player", "type": "引导", "affinity": 40}], "location_id": f"loc_{i + 1}",
              "mood": "平静", "avatar_emoji": e} for i, (n, r, p, g, e) in enumerate(t["characters"])]
    key = sorted(sents, key=len, reverse=True)[:6]
    cards = [{"id": f"k_{i + 1}", "title": f"知识点{i + 1}：{s[:10]}…", "content": s, "source": f"《{ttl}》原文"}
             for i, s in enumerate(sorted(key, key=sents.index))]
    return {
        "title": f"走进《{ttl}》", "genre": t["genre"] + (f"·{subject}" if subject else ""), "tone": t["tone"], "era": era,
        "setting": "你将穿越进原文描绘的世界：" + "".join(sents[:2])[:150], "premise": sents[0][:100],
        "initial_conflict": "要真正理解这段内容，你需要亲身走进它，向亲历者求证每一个细节。",
        "player": {"name": "你", "role": "求知的学子"}, "locations": locs, "characters": chars,
        "items": [{"id": f"it_{i + 1}", "name": n, "description": d, "owner_id": "player"} for i, (n, d) in enumerate(t["items"])],
        "stats": dict(t["stats"]),
        "opening_scene": f"一阵墨香过后，你睁开眼，发现自己置身于《{ttl}》的世界。讲述先生拱手笑道：“你来得正好。”他指着远处说：“{sents[0][:60]}”",
        "opening_options": [{"id": "opt_1", "text": "向讲述先生请教背景"}, {"id": "opt_2", "text": "去历史现场看看"},
                            {"id": "opt_3", "text": "和同窗小友讨论原文"}],
        "knowledge_cards": cards,
    }


NARRATION_BITS = {
    "open": ["你{act}。", "你决定{act}。", "片刻犹豫后，你{act}。"],
    "scene": ["{loc}里，{desc}。", "此刻的{loc}，{desc}。"],
    "npc": ["{npc}{npc_action}，低声说：“{line}”", "{npc}看了你一眼，{npc_action}。“{line}”"],
    "event": ["你隐约听说：{event}", "街头巷尾传来消息——{event}"],
    "inject": ["就在这时，异变陡生：{inject}。所有人都愣住了。"],
    "hook": ["你意识到，事情远比表面复杂。", "一个新的疑问在你心中升起。", "远处似乎有人在注视着你。", "线索开始连成一条若隐若现的线。"],
}
NPC_LINES = ["这件事你最好别管。", "我知道的都告诉你了……也许还不止这些。", "你来得正是时候。", "小心身边的人。",
             "有些真相，知道了就回不去了。", "跟我来，我给你看样东西。"]
NPC_ACTIONS = ["放下手中的东西", "压低了声音", "皱起眉头", "露出意味深长的笑", "警惕地环顾四周", "递给你一张纸条"]


def second_person(action: str) -> str:
    """玩家行动转第二人称片段：“我去码头” → “去码头”，句中“我”→“你”。"""
    act = action.strip().rstrip("。.!！")
    act = re.sub(r"^(?:我|你)(?:们)?", "", act)
    return act.replace("我", "你") or "环顾四周"


def detect_location(world: Any, action: str) -> str | None:
    """从行动文本识别目的地：全名 > 名称后两字（如“码头”“茶楼”）。"""
    best = None
    for l in world.locations:
        if not l.name:
            continue
        if l.name in action:
            return l.id
        if best is None and len(l.name) >= 3 and l.name[-2:] in action:
            best = l.id
    return best


def narrate(world: Any, action: str, focus: Any | None, events: list[str], injects: list[str], turn: int) -> str:
    rng = seed_rng(world.id, turn, action)
    loc = world.loc(world.state.player_location_id)
    act = second_person(action)
    parts = [rng.choice(NARRATION_BITS["open"]).format(act=act)]
    if loc:
        parts.append(rng.choice(NARRATION_BITS["scene"]).format(loc=loc.name, desc=loc.description))
    for inj in injects:
        parts.append(rng.choice(NARRATION_BITS["inject"]).format(inject=inj.rstrip("。")))
    if focus:
        parts.append(rng.choice(NARRATION_BITS["npc"]).format(npc=focus.name, npc_action=rng.choice(NPC_ACTIONS),
                                                            line=rng.choice(NPC_LINES)))
    for e in events[:1]:
        parts.append(rng.choice(NARRATION_BITS["event"]).format(event=e.rstrip("。") + "。"))
    if world.mode == "education" and world.knowledge_cards:
        k = world.knowledge_cards[turn % len(world.knowledge_cards)]
        parts.append(f"讲述先生补充道：“{k.content}”")
    parts.append(rng.choice(NARRATION_BITS["hook"]))
    return "".join(parts)


def options_for(world: Any, turn: int) -> list[dict[str, str]]:
    rng = seed_rng(world.id, turn, "opt")
    loc = world.loc(world.state.player_location_id)
    opts: list[str] = []
    npcs_here = [c for c in world.npcs() if c.location_id == world.state.player_location_id]
    if npcs_here:
        opts.append(f"向{rng.choice(npcs_here).name}追问细节")
    if loc and loc.interactables:
        opts.append(f"调查{rng.choice(loc.interactables)}")
    if loc and loc.connections:
        nxt = world.loc(rng.choice(loc.connections))
        if nxt:
            opts.append(f"前往{nxt.name}")
    for extra in ["整理手头的线索", "暂时观望，静观其变", "找个可靠的人商量"]:
        if len(opts) >= 3:
            break
        opts.append(extra)
    return [{"id": f"opt_{i + 1}", "text": o} for i, o in enumerate(opts[:3])]
