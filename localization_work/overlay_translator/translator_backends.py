"""可配置的多后端翻译模块（适配国内网络）。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Optional

from game_string_db import get_game_string_db
from ko_zh_db import get_ko_zh_db

HANGUL_RE = re.compile(r"[\uAC00-\uD7AF\u3131-\u318E]+")

# Trickcal Revive UI 词典（优先于机器翻译，避免 퀘스트→吻、캐시상점→商店 等）
KO_GAME_GLOSSARY: dict[str, str] = {
    "캐시 상점": "点券商店",
    "캐시상점": "点券商店",
    "캐시": "点券",
    "모집": "招募",
    "상점": "商店",
    "사도": "使徒",
    "카드": "卡牌",
    "무장": "武装",
    "극장": "剧场",
    "교단": "教团",
    "모험": "冒险",
    "강해지기": "变强",
    "빠르게 강해지기": "快速变强",
    "레벨 패스": "等级通行证",
    "레벨패스": "等级通行证",
    "레벨": "等级",
    "레벨 파스": "等级通行证",
    "트릭컬 패스": "Trickcal通行证",
    "트릭컬패스": "Trickcal通行证",
    "스텝업 패키지": "阶梯礼包",
    "스텝업패키지": "阶梯礼包",
    "이벤트": "活动",
    "이벤트 팝업": "活动弹窗",
    "이벤트팝업": "活动弹窗",
    "퀘스트": "任务",
    "친구": "好友",
    "출석체크": "签到",
    "출석 체크": "签到",
    "평일 농장": "平日农场",
    "평일농장": "平日农场",
    "패스": "通行证",
    "제발 그만 쉬고 싸우기": "求你别再休息快战斗",
    "다시 받기": "重新领取",
    "세이용가": "适龄",
    "소리 없는 기도자의 사정": "无声祈祷者的情况",
    "속성별 공략": "属性攻略",
    "은의 용족의 초대": "银龙族邀请",
    "용족의 초대": "龙族邀请",
    "갱신": "刷新",
    "팝업": "弹窗",
    "공략": "攻略",
    "초대": "邀请",
    "농장": "农场",
    "방과 후 새싹 교실": "课后新芽教室",
    "왕사탕": "主糖",
    "왕사탕 회복 완료": "主糖恢复完成",
}

# OCR 常见误读 → 归一化（尤其底部按钮 / 任务图标）
OCR_KO_NORMALIZE: dict[str, str] = {
    "퀘스": "퀘스트",
    "퀘스 트": "퀘스트",
    "퀘스터": "퀘스트",
    "캐시 상점": "캐시상점",
    "캐시 점": "캐시상점",
    "캐시점": "캐시상점",
    "모집 ": "모집",
    "상 점": "상점",
    "사 도": "사도",
    "카 드": "카드",
    "무 장": "무장",
    "교 단": "교단",
    "모 험": "모험",
    "레벨 파스": "레벨패스",
    "레벨 패스": "레벨패스",
    "레벨파스": "레벨패스",
    "트릭컬 파스": "트릭컬패스",
}

# 机器翻译对 UI 短词常见幻觉，命中则丢弃
_BAD_UI_MT = frozenset({
    "杀死", "杀", "死亡", "死", "重生", "吻", "亲吻", "接吻",
    "全站", "记录", "副本", "那", "卡",
})

_FUZZY_UI_THRESHOLD = 0.55
_SHORT_UI_MAX_LEN = 12


def contains_hangul(text: str) -> bool:
    return bool(HANGUL_RE.search(text or ""))


def _compact_ko(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _normalize_ocr_ko(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\uAC00-\uD7AF\u3131-\u318EA-Za-z0-9\s·\-]", "", t)
    t = t.strip()
    if t in OCR_KO_NORMALIZE:
        t = OCR_KO_NORMALIZE[t]
    compact = _compact_ko(t)
    if compact in OCR_KO_NORMALIZE:
        t = OCR_KO_NORMALIZE[compact]
    return t.strip()


GAME_MT_PREFIX = (
    "【游戏UI】手游 Trickcal Revive 界面按钮/菜单韩文，"
    "译成一条简短中文游戏用语，不要引号、不要解释："
)


def _glossary_keys_by_length() -> List[str]:
    return sorted(KO_GAME_GLOSSARY.keys(), key=lambda k: len(_compact_ko(k)), reverse=True)


def _match_glossary_key(text: str) -> Optional[str]:
    """返回匹配到的词典韩文键（优先更长、更具体的键）。"""
    raw = _normalize_ocr_ko(text)
    if not raw:
        return None
    if raw in KO_GAME_GLOSSARY:
        return raw
    compact = _compact_ko(raw)
    for key in _glossary_keys_by_length():
        if _compact_ko(key) == compact:
            return key
    best_key: Optional[str] = None
    best_score = 0.0
    for key in _glossary_keys_by_length():
        kc = _compact_ko(key)
        if len(kc) < 2:
            continue
        if kc in compact:
            return key
        # 禁止「상점」误匹配「캐시상점」：短 OCR 不可仅因是长键子串而命中
        if compact in kc and len(compact) >= max(3, int(len(kc) * 0.75)):
            return key
        score = SequenceMatcher(None, compact, kc).ratio()
        if score > best_score:
            best_score = score
            best_key = key
    if best_key and best_score >= _FUZZY_UI_THRESHOLD:
        return best_key
    return None


def lookup_glossary(text: str) -> Optional[str]:
    key = _match_glossary_key(text)
    return KO_GAME_GLOSSARY[key] if key else None


def fuzzy_match_glossary_key(text: str) -> Optional[str]:
    return _match_glossary_key(text)


def _build_candidate_pool(primary: str, candidates: Optional[List[str]]) -> List[str]:
    pool: List[str] = []
    for item in [primary, *(candidates or [])]:
        n = _normalize_ocr_ko(item)
        if n and n not in pool:
            pool.append(n)
    return pool


def reconstruct_compound_from_pool(pool: List[str]) -> Optional[str]:
    """从 OCR 候选片段重建复合 UI 词（如 캐시 + 상점 → 캐시상점）。"""
    if not pool:
        return None

    has_cash = False
    has_shop = False
    for p in pool:
        c = _compact_ko(p)
        if not c:
            continue
        if c == "캐시상점" or c == "캐시 상점":
            return "캐시상점"
        if "캐시" in c:
            has_cash = True
        if c == "상점":
            has_shop = True
    if has_cash and has_shop:
        return "캐시상점"

    for order in (pool, list(reversed(pool))):
        joined = _compact_ko("".join(order))
        key = _match_glossary_key(joined)
        if key and _compact_ko(key) == joined:
            return key

    return None


def resolve_ui_ko_label(primary: str, candidates: Optional[List[str]] = None) -> str:
    """从 OCR 候选中选出最可能的 UI 韩文词条（优先更长、更具体的词典键）。"""
    pool = _build_candidate_pool(primary, candidates)
    if not pool:
        return _normalize_ocr_ko(primary)

    compound = reconstruct_compound_from_pool(pool)
    if compound:
        return compound

    matched_keys: List[tuple[int, float, str]] = []
    for p in pool:
        key = _match_glossary_key(p)
        if key:
            score = SequenceMatcher(None, _compact_ko(p), _compact_ko(key)).ratio()
            matched_keys.append((len(_compact_ko(key)), score, key))
    if matched_keys:
        matched_keys.sort(key=lambda x: (x[0], x[1]), reverse=True)
        return matched_keys[0][2]

    return max(pool, key=lambda p: (len(_compact_ko(p)), len(p)))


def translate_glossary_from_pool(primary: str, candidates: Optional[List[str]] = None) -> Optional[str]:
    """仅词典：遍历全部 OCR 候选，返回最佳中文。"""
    pool = _build_candidate_pool(primary, candidates)
    compound = reconstruct_compound_from_pool(pool)
    if compound and compound in KO_GAME_GLOSSARY:
        return KO_GAME_GLOSSARY[compound]

    best: Optional[tuple[int, float, str]] = None
    for p in pool:
        key = _match_glossary_key(p)
        if not key:
            continue
        score = SequenceMatcher(None, _compact_ko(p), _compact_ko(key)).ratio()
        item = (len(_compact_ko(key)), score, KO_GAME_GLOSSARY[key])
        if best is None or item > best:
            best = item
    return best[2] if best else None


def _sanitize_zh_output(text: str, *, preserve_newlines: bool = False) -> str:
    t = (text or "").strip()
    if not t:
        return ""

    for marker in ("【游戏UI】", "【游戏UI翻译】", "【游戏剧情】", "请按游戏", "仅输出译文", "不要引号"):
        if marker in t:
            parts = re.split(r"[：:\n]", t, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                t = parts[1].strip()
            break

    split_seps = (" / ", "/", "；", ";", "|", "、")
    if not preserve_newlines:
        split_seps = split_seps + ("\n",)
    for sep in split_seps:
        if sep in t:
            t = t.split(sep)[0].strip()
            break

    t = re.sub(r"[（(][^）)]*[）)]", "", t).strip()
    # 去掉 Bing 等返回的多余引号
    t = t.strip("\"'""''「」『』《》""''")
    if preserve_newlines:
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
    else:
        t = re.sub(r"\s+", " ", t)
    return t


GAME_DIALOG_MT_PREFIX = (
    "【游戏剧情】手游 Trickcal Revive 韩文对话/说明，"
    "译成自然流畅的中文，保留换行，不要引号、不要解释："
)


def translate_ko_to_zh(text: str, engine: str = "bing", *, dialog: bool = False) -> str:
    text = _normalize_ocr_ko(text)
    if not text:
        return ""

    prefix = GAME_DIALOG_MT_PREFIX if dialog else GAME_MT_PREFIX
    payload = f"{prefix}\n{text}"

    if engine == "google":
        from deep_translator import GoogleTranslator
        return GoogleTranslator(source="ko", target="zh-CN").translate(text)

    import translators as ts
    eng_map = {
        "bing": "bing",
        "alibaba": "alibaba",
        "baidu": "baidu",
    }
    name = eng_map.get(engine, "bing")
    return ts.translate_text(payload, translator=name, from_language="ko", to_language="zh")


def _retranslate_hangul_segments(text: str, engine: str) -> str:
    if not contains_hangul(text):
        return text.strip()

    out: list[str] = []
    pos = 0
    for m in HANGUL_RE.finditer(text):
        if m.start() > pos:
            out.append(text[pos : m.start()])
        segment = m.group()
        gloss = lookup_glossary(segment)
        if gloss:
            out.append(gloss)
        else:
            try:
                out.append(_sanitize_zh_output(translate_ko_to_zh(segment, engine)))
            except Exception:
                out.append(segment)
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return re.sub(r"\s+", " ", "".join(out).strip())


def translate_ui_label(
    text: str,
    primary: str = "bing",
    fallback: Optional[str] = "alibaba",
    candidates: Optional[List[str]] = None,
    *,
    paragraph: bool = False,
) -> str:
    """
    UI 标签翻译：全候选词典匹配 → 长文本才机器翻译。
    短 UI 禁止不可靠 MT（避免 사도→杀死、퀘스트→重生）。
    """
    if paragraph or "\n" in (text or ""):
        return translate_paragraph_text(text, primary, fallback, candidates)

    gloss = translate_glossary_from_pool(text, candidates)
    if gloss:
        return gloss

    pool = _build_candidate_pool(text, candidates)
    for p in pool:
        paired = lookup_ko_zh_table(p)
        if paired:
            return paired

    if len(pool) >= 2:
        joined = " ".join(pool)
        gloss2 = lookup_glossary(joined)
        if gloss2:
            return gloss2
        joined_compact = _compact_ko("".join(pool))
        for key in _glossary_keys_by_length():
            if _compact_ko(key) == joined_compact:
                return KO_GAME_GLOSSARY[key]

    src = resolve_ui_ko_label(text, candidates)
    compact = _compact_ko(src)
    hangul_chars = len(HANGUL_RE.findall(compact))

    if hangul_chars <= _SHORT_UI_MAX_LEN:
        for eng in [primary, fallback]:
            if not eng:
                continue
            try:
                result = _sanitize_zh_output(translate_ko_to_zh(src, eng))
                if (
                    result
                    and not contains_hangul(result)
                    and result not in _BAD_UI_MT
                    and len(result) <= 14
                ):
                    return result
            except Exception:
                continue
        return ""

    return translate_game_text(src, primary, fallback)


def _refine_with_game_strings(zh_text: str, *, paragraph: bool = False) -> str:
    """机翻结果与国服 APK 文本池模糊匹配，命中则替换为官方译法。"""
    if not zh_text or contains_hangul(zh_text):
        return zh_text
    refined = get_game_string_db().refine_translation(zh_text, paragraph=paragraph)
    return refined if refined else zh_text


def lookup_ko_zh_table(text: str) -> Optional[str]:
    """Frida 配对表 / 运行时抓取生成的韩中对照。"""
    return get_ko_zh_db().lookup(text)


def translate_game_text(
    text: str,
    primary: str = "bing",
    fallback: Optional[str] = "alibaba",
    *,
    dialog: bool = False,
) -> str:
    src = _normalize_ocr_ko(text)
    if not src:
        return ""

    gloss = lookup_glossary(src)
    if gloss:
        return gloss

    paired = lookup_ko_zh_table(src)
    if paired:
        return paired

    engines = [primary]
    if fallback and fallback != primary:
        engines.append(fallback)

    last_result = src
    for eng in engines:
        try:
            result = _sanitize_zh_output(
                translate_ko_to_zh(src, eng, dialog=dialog),
                preserve_newlines=dialog,
            )
            result = _retranslate_hangul_segments(result, eng)
            result = _refine_with_game_strings(result, paragraph=dialog)
            last_result = result
            if result and not contains_hangul(result):
                return result
        except Exception:
            continue

    for eng in engines:
        last_result = _sanitize_zh_output(
            _retranslate_hangul_segments(last_result, eng),
            preserve_newlines=dialog,
        )
        last_result = _refine_with_game_strings(last_result, paragraph=dialog)
        if last_result and not contains_hangul(last_result):
            return last_result
    return last_result


def translate_paragraph_text(
    text: str,
    primary: str = "bing",
    fallback: Optional[str] = "alibaba",
    candidates: Optional[List[str]] = None,
) -> str:
    """多行段落：优先整段翻译保留语境，失败再逐行。"""
    raw = (text or "").strip()
    if not raw:
        return ""

    if "\n" not in raw and len(raw) > 30:
        parts = re.split(r"(?<=[\.!?…])\s+", raw)
        if len(parts) >= 2:
            raw = "\n".join(p.strip() for p in parts if p.strip())

    if "\n" not in raw:
        gloss = translate_glossary_from_pool(raw, candidates)
        if gloss:
            return gloss

    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    if not lines:
        return ""

    src_chars = sum(len(ln) for ln in lines)
    if len(lines) >= 2 or src_chars > 22:
        block = translate_game_text(raw, primary, fallback, dialog=True)
        block = _refine_with_game_strings(block, paragraph=True)
        if block and not contains_hangul(block) and len(block) >= max(6, int(src_chars * 0.22)):
            return block

    out: List[str] = []
    for ln in lines:
        line_gloss = translate_glossary_from_pool(ln, candidates)
        if line_gloss:
            out.append(line_gloss)
            continue
        line_candidates = [c for c in (candidates or []) if c.strip()]
        translated = translate_ui_label(
            ln, primary=primary, fallback=fallback, candidates=line_candidates or None,
        )
        if translated and not contains_hangul(translated):
            out.append(translated)
            continue
        mt = translate_game_text(ln, primary, fallback, dialog=True)
        out.append(mt if mt else ln)
    return "\n".join(out)


def translate_with_fallback(
    text: str,
    primary: str = "bing",
    fallback: Optional[str] = "alibaba",
    candidates: Optional[List[str]] = None,
) -> str:
    return translate_ui_label(text, primary, fallback, candidates)
