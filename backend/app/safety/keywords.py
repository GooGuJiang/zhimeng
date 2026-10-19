"""Keyword lists for the first (local, free) stage of F9 content safety.

Design notes
- Hard-block categories are blocked regardless of LLM verdict (cheap, deterministic).
- Fiction is allowed to contain conflict (a detective story may have a murder), so generic
  violence words only raise the *rating*; they are not blocked.
- Crisis patterns are first-person expressions; a bare "自杀" (e.g. "调查自杀案") is only a
  hint that triggers LLM moderation.
"""
from __future__ import annotations

import re

# category -> keywords. All matching is case-insensitive on normalised text.
HARD_BLOCK: dict[str, list[str]] = {
    "sexual_minors": ["幼女", "萝莉色情", "儿童色情", "未成年色情", "恋童", "童妓", "child porn", "cp资源"],
    "sexual_explicit": ["性交", "口交", "肛交", "做爱细节", "裸照", "色情片", "黄片", "约炮", "porn", "强奸"],
    "terrorism": ["制造炸弹", "制作炸弹", "炸弹制作", "做炸弹", "造炸弹", "恐怖袭击教程", "人体炸弹", "自制炸药", "圣战招募"],
    "weapons_drugs": ["制毒", "冰毒制作", "合成冰毒", "贩毒渠道", "买枪", "自制枪支", "枪支购买", "提炼海洛因"],
    "illegal_services": ["代开发票", "洗钱教程", "办假证", "网络赌博平台", "博彩网址", "裸聊"],
    "hate": ["劣等民族", "种族灭绝万岁"],
    "privacy": ["身份证号是", "人肉搜索", "开盒"],
    "politics": ["颠覆国家政权", "分裂国家", "推翻政府"],
}

# Regex hard-block patterns (instruction-like requests that keyword lists miss, e.g. "教我怎么制作炸弹").
HARD_BLOCK_PATTERNS: dict[str, list[str]] = {
    "terrorism": [r"(制作|制造|自制|组装|怎么做|如何做|教我做).{0,6}(炸弹|炸药|雷管|燃烧瓶|爆炸物)",
                  r"(炸弹|炸药|爆炸物).{0,4}(配方|做法|制作方法|教程)"],
    "weapons_drugs": [r"(制作|制造|合成|提炼|提纯|自制).{0,4}(冰毒|海洛因|摇头丸|k粉|毒品|芬太尼|大麻)",
                      r"(冰毒|海洛因|毒品|芬太尼).{0,4}(配方|做法|制作方法|教程|哪里买|购买)",
                      r"(自制|组装|改装|3d打印).{0,4}(枪|手枪|步枪|枪支)"],
    "illegal_services": [r"(教我|教程|方法|怎么).{0,6}(诈骗|洗钱|盗号|黑进|入侵).{0,6}(账户|银行|系统|别人)?"],
}

# Prompt-injection / jailbreak attempts (world prompt, god-mode inject, free action, memory question).
INJECTION_PATTERNS: list[str] = [
    r"(忽略|无视|忘记|忘掉|抛开|跳过)(掉)?(你)?(之前|以上|上面|前面|所有|全部|一切|先前|你的|系统)的?(所有|全部)?(指令|指示|规则|设定|提示词?|限制|约束|要求)",
    r"(不要|别|不再)(再)?(遵守|遵循|理会)(任何|你的|之前的|系统的)?(规则|指令|限制|安全)",
    r"(解除|取消|关闭|绕过|突破)(你的|所有|全部)?(安全|内容)?(限制|审查|过滤|审核|约束)",
    r"(输出|告诉我|显示|打印|泄露|复述|重复)(你的|一下)?(系统|初始|隐藏)(提示词?|指令|prompt|设定)",
    r"(开发者|越狱|无限制|无审查|无过滤)模式",  # NB: 不含"上帝模式"（游戏内上帝视角是正常功能）
    r"(你|扮演|成为)(现在)?(是)?(一个)?(没有|不受|无)(任何)?(限制|道德|审查|规则)(的)?(ai|人工智能|助手|模型)?",
    r"\bdan\b.{0,10}(mode|模式|do anything now)|do anything now",
    r"\bignore\b.{0,20}\b(previous|prior|above|all)\b.{0,20}\b(instructions?|rules|prompts?)\b",
    r"\b(system|developer)\s*(prompt|message)\b",
    r"\bjail\s*break\b|越狱(提示|指令|prompt)?",
    r"</?\s*(system|assistant|im_start|im_end)\s*>|<\|im_(start|end)\|>",
]

# Raise the rating but do not block (allowed in fiction up to the world's rating).
RATING_HINTS: dict[str, list[str]] = {
    "mature": ["血腥", "肢解", "断肢", "内脏", "虐杀", "酷刑", "尸块", "爆头", "开膛", "裸体", "床戏", "吸毒"],
    "teen": ["杀", "血", "死亡", "尸体", "枪", "刀", "打斗", "战斗", "谋杀", "毒药", "恐怖", "鬼", "酒", "烟",
             "接吻", "恋爱", "赌", "绑架", "复仇", "暴力"],
}

# Extra blocks only for minor mode (未成年人模式).
MINOR_BLOCK: dict[str, list[str]] = {
    "minor_unsuitable": ["喝酒", "抽烟", "吸烟", "赌博", "下注", "恋爱", "接吻", "约会", "上床", "暧昧", "网贷",
                         "氪金", "充值", "血腥", "虐杀", "酷刑", "裸"],
}

# First-person crisis expressions → crisis intercept.
CRISIS_PATTERNS: list[str] = [
    r"我(真的|好|很|已经|实在)?(想|要|打算|准备)(去)?(死|自杀|轻生|自尽|结束(自己|我)的?生命)",
    r"(不想|不愿意?)(再)?活(下去|了)",
    r"活着(没|没有)(意思|意义)",
    r"(想|要)(割腕|跳楼|跳河|上吊|吃安眠药|烧炭)",
    r"我(在|已经)?(自残|割腕|伤害自己)",
    r"(帮我|教我|告诉我).{0,6}(自杀|轻生|无痛.{0,2}死)",
    r"(怎么|如何|什么方法).{0,6}(自杀|死得?(快|无痛)|结束生命)",
    r"\b(kill myself|suicide|end my life|self[- ]harm)\b",
    r"遗书.{0,4}(写好|准备)",
]
CRISIS_HINTS = ["自杀", "轻生", "自残", "割腕", "跳楼", "抑郁", "绝望", "活不下去", "想死"]

_CRISIS_RE = [re.compile(p, re.I) for p in CRISIS_PATTERNS]
_HARD_RE = {cat: [re.compile(p, re.I) for p in ps] for cat, ps in HARD_BLOCK_PATTERNS.items()}
_INJECTION_RE = [re.compile(p, re.I) for p in INJECTION_PATTERNS]
_SPACE_RE = re.compile(r"[\s\u200b\u200c\u200d\ufeff·.,_\-*~、，。！？!?]+")


def normalize(text: str) -> str:
    """Lower-case and strip separators so that "制 毒" / "制*毒" still match."""
    t = (text or "").lower()
    # full-width → half-width
    t = "".join(chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in t)
    return _SPACE_RE.sub("", t)


def find(text: str, table: dict[str, list[str]]) -> dict[str, list[str]]:
    n = normalize(text)
    hits: dict[str, list[str]] = {}
    for cat, words in table.items():
        found = [w for w in words if normalize(w) in n]
        if found:
            hits[cat] = found
    return hits


def crisis_match(text: str) -> bool:
    raw = text or ""
    return any(r.search(raw) for r in _CRISIS_RE) or any(r.search(normalize(raw)) for r in _CRISIS_RE)


def find_patterns(text: str) -> dict[str, list[str]]:
    """Regex hard-block hits on raw + normalised text → {category: [matched snippet, ...]}."""
    raw, n = text or "", normalize(text)
    hits: dict[str, list[str]] = {}
    for cat, regs in _HARD_RE.items():
        found = [m.group(0) for r in regs for t in (raw, n) if (m := r.search(t))]
        if found:
            hits[cat] = sorted(set(found))
    return hits


def hard_hits(text: str) -> dict[str, list[str]]:
    """Keyword + regex hard-block hits merged."""
    hits = find(text, HARD_BLOCK)
    for cat, ws in find_patterns(text).items():
        hits[cat] = sorted(set(hits.get(cat, []) + ws))
    return hits


def injection_match(text: str) -> bool:
    raw = text or ""
    n = normalize(raw)
    return any(r.search(raw) or r.search(n) for r in _INJECTION_RE)


def crisis_hint(text: str) -> bool:
    n = normalize(text)
    return any(h in n for h in CRISIS_HINTS)


def mask(text: str, words: list[str]) -> str:
    """Replace each occurrence of the words with ＊ (same length)."""
    out = text
    for w in sorted(set(words), key=len, reverse=True):
        if w:
            out = re.sub(re.escape(w), "＊" * len(w), out, flags=re.I)
    return out


# ---- fast streaming filter (filter_chunk) ----
def _alternation(words: list[str]) -> re.Pattern[str]:
    uniq = sorted({w for w in words if w}, key=len, reverse=True)
    return re.compile("|".join(re.escape(w) for w in uniq), re.I)


_CHUNK_RE = _alternation([w for ws in HARD_BLOCK.values() for w in ws])
_CHUNK_MINOR_RE = _alternation([w for ws in HARD_BLOCK.values() for w in ws]
                               + [w for ws in MINOR_BLOCK.values() for w in ws]
                               + RATING_HINTS["mature"])


def mask_fast(text: str, minor_mode: bool = False) -> str:
    """Single precompiled regex pass (used for every streamed token chunk)."""
    if not text:
        return text
    r = _CHUNK_MINOR_RE if minor_mode else _CHUNK_RE
    return r.sub(lambda m: "＊" * len(m.group(0)), text)
