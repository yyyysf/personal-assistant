"""LLM 业务封装：摘要、周复盘、学习路线、书单抽取，均带本地降级。"""

import json
import re
from typing import Any

from src.core.config import settings
from src.core.logging import get_logger
from src.llm import prompts
from src.llm.client import LLMError, LLMNotConfigured, chat

logger = get_logger(__name__)


def is_available() -> bool:
    return settings.llm_configured


def _clean_text(text: str, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, stripped)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    return None


def summarize_paper(title: str, abstract: str, authors: str = "") -> str:
    try:
        return chat(
            prompts.PAPER_SUMMARY.format(title=title, authors=authors, abstract=abstract[:4000]),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.2,
        )
    except (LLMNotConfigured, LLMError) as exc:
        logger.info("论文摘要降级：%s", exc)
        return f"（本地摘要）{_clean_text(abstract, 220)}"


def summarize_news(title: str, source: str, content: str) -> str:
    try:
        return chat(
            prompts.NEWS_SUMMARY.format(title=title, source=source, content=content[:3000]),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.2,
            max_tokens=200,
        )
    except (LLMNotConfigured, LLMError):
        return _clean_text(content or title, 100)


def suggest_tags(title: str, abstract: str) -> str:
    try:
        tags = chat(
            prompts.PAPER_TAGS.format(title=title, abstract=abstract[:2000]),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.1,
            max_tokens=80,
        )
        cleaned = re.sub(r"[^\w一-鿿,，\s]", "", tags)
        return ",".join(part.strip() for part in re.split(r"[,，]", cleaned) if part.strip())[:200]
    except (LLMNotConfigured, LLMError):
        return "arXiv,cs.AI"


def generate_daily_digest(items: list[dict[str, str]]) -> str:
    if not items:
        return "今日暂无可聚合的资讯。"
    item_lines = "\n".join(
        f"- [{item['source']}] {item['title']}\n  {item.get('summary', '')}" for item in items
    )
    try:
        return chat(
            prompts.DAILY_DIGEST.format(items=item_lines),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.4,
        )
    except (LLMNotConfigured, LLMError):
        lines = [f"今日共聚合 {len(items)} 条 AI 前沿资讯：", ""]
        for index, item in enumerate(items[:6], start=1):
            lines.append(f"{index}. **{item['title']}**（{item['source']}）")
            if item.get("summary"):
                lines.append(f"   {item['summary']}")
        lines.extend(["", "> 本地降级简报：配置 DEEPSEEK_API_KEY 后可获得 LLM 精炼版本。"])
        return "\n".join(lines)


def generate_weekly_review(payload: dict) -> tuple[str, str, str]:
    """返回 (content, suggestions, source)。"""
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    try:
        text = chat(
            prompts.WEEKLY_REVIEW.format(payload=payload_text),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.4,
            max_tokens=2000,
        )
        return text, "", "llm"
    except (LLMNotConfigured, LLMError) as exc:
        logger.info("周复盘降级：%s", exc)
        completion = payload.get("completion", {})
        done_tasks = payload.get("tasks_done", [])
        pending = payload.get("tasks_pending", [])
        learning = payload.get("learning_done", [])
        content = (
            f"### 本周回顾\n"
            f"本周任务执行率 {completion.get('rate', 0)}%，完成 {completion.get('done', 0)} 项，"
            f"待推进 {len(pending)} 项；连续记录 {payload.get('streak', 0)} 天。\n\n"
            f"- 完成任务：{'、'.join(task['title'] for task in done_tasks[:5]) or '暂无'}\n"
            f"- 学习进展：{'、'.join(learning[:5]) or '暂无新的学习完成记录'}\n"
            f"- 资讯摄入：本周聚合 {payload.get('news_count', 0)} 条 AI 前沿资讯。\n\n"
            f"亮点在于保持了每日行动节奏；不足是任务清单偏多时容易分散注意力，"
            f"科研阅读的深度笔记尚未形成稳定产出。"
        )
        suggestions = (
            f"1. 明天优先完成「{pending[0]['title'] if pending else '本周最重要的一项任务'}」，"
            f"给 60 分钟不被打断的时间块。\n"
            f"2. 本周至少完成 1 篇论文的结构化笔记，并写入 Zotero。\n"
            f"3. 将每天的学习任务控制在 2 项以内，避免进度焦虑。\n"
            f"4. 周末检查书单，选一本进入精读状态。"
        )
        return content, suggestions, "fallback"


def generate_learning_plan(
    category: str,
    category_label: str,
    progress: int,
    done_items: list[str],
    open_items: list[str],
    logs: list[str],
) -> list[dict[str, Any]]:
    try:
        text = chat(
            prompts.LEARNING_PLAN.format(
                category_label=category_label,
                progress=progress,
                done_items="、".join(done_items) or "暂无",
                open_items="、".join(open_items) or "暂无",
                logs="；".join(logs) or "暂无",
            ),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.5,
        )
        data = _extract_json(text)
        if isinstance(data, list):
            plan = []
            for item in data:
                if isinstance(item, dict) and item.get("title"):
                    plan.append(
                        {
                            "title": str(item["title"])[:200],
                            "description": str(item.get("description", ""))[:500],
                            "resource_url": str(item.get("resource_url", ""))[:600],
                            "mastery_target": int(item.get("mastery_target", 15) or 15),
                        }
                    )
            if plan:
                return plan[:3]
    except (LLMNotConfigured, LLMError, ValueError, TypeError) as exc:
        logger.info("学习路线降级：%s", exc)

    if category == "music":
        return [
            {
                "title": "复习和弦进行：I–V–vi–IV",
                "description": "用钢琴或 MIDI 键盘弹奏 10 分钟，并记录听感。",
                "resource_url": "",
                "mastery_target": 20,
            },
            {
                "title": "跑通 MusicGen 最小示例",
                "description": "用一句描述生成 15 秒片段，比较两个随机种子的差异。",
                "resource_url": "https://github.com/facebookresearch/audiocraft",
                "mastery_target": 30,
            },
            {
                "title": "沉淀一条学习记忆",
                "description": "记录今天最反直觉的一个知识点，方便下次动态调整路线。",
                "resource_url": "",
                "mastery_target": 10,
            },
        ]
    return [
        {
            "title": "复述扩散模型的训练目标",
            "description": "不看资料，用 5 句话解释前向加噪与反向去噪。",
            "resource_url": "",
            "mastery_target": 20,
        },
        {
            "title": "对比时空注意力与图像注意力",
            "description": "手画一次张量形状变化，写 3 行对照笔记。",
            "resource_url": "",
            "mastery_target": 30,
        },
        {
            "title": "观看一节最小视频扩散教程",
            "description": "只看 20 分钟，记下可在本地复现的关键依赖。",
            "resource_url": "",
            "mastery_target": 15,
        },
    ]


def extract_books(notes_text: str) -> list[dict[str, str]]:
    """从笔记文本提取书单，LLM 不可用时用《书名》正则降级。"""
    try:
        text = chat(
            prompts.BOOK_EXTRACTION.format(notes=notes_text[:6000]),
            system=prompts.SYSTEM_ASSISTANT,
            temperature=0.2,
        )
        data = _extract_json(text)
        if isinstance(data, list):
            books = []
            for item in data:
                if isinstance(item, dict) and item.get("title"):
                    books.append(
                        {
                            "title": str(item["title"]).strip()[:300],
                            "author": str(item.get("author", "")).strip()[:200],
                            "reason": str(item.get("reason", "")).strip()[:200],
                        }
                    )
            if books:
                return _dedupe_books(books)
    except (LLMNotConfigured, LLMError) as exc:
        logger.info("书单抽取降级：%s", exc)

    titles = re.findall(r"《([^》]{1,60})》", notes_text)
    return _dedupe_books(
        [{"title": title.strip(), "author": "", "reason": "来自小红书笔记"} for title in titles]
    )


def _dedupe_books(books: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for book in books:
        key = book["title"].strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(book)
    return result
