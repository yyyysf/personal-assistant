"""首次启动演示数据。设置 SEED_DEMO_DATA=false 可关闭。"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.core.logging import get_logger
from src.core.tags import ensure_tags, normalize_tags
from src.core.time_utils import days_ago, today
from src.models import (
    Book,
    LearningItem,
    LearningLog,
    LearningTrack,
    NewsDigest,
    NewsItem,
    Paper,
    Place,
    Task,
)

logger = get_logger(__name__)


def _at(day: date, hour: int = 10, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute))


def seed_demo_data(db: Session) -> None:
    if db.scalar(select(Task).limit(1)) is not None:
        return

    logger.info("首次启动：写入演示数据")
    current_day = today()

    tasks = [
        Task(
            title="梳理 arXiv cs.AI 今日论文并标注重点",
            description="重点关注 LLM Agent 与多模态方向",
            status="done",
            priority="high",
            tags="科研,论文",
            due_date=_at(current_day, 18),
            completed_at=_at(current_day, 9, 30),
        ),
        Task(
            title="完成 AI 视频学习第 3 节：扩散模型直觉",
            status="done",
            priority="high",
            tags="学习,视频",
            completed_at=_at(current_day, 11, 0),
        ),
        Task(
            title="整理小红书收藏的 AI 书单",
            status="done",
            priority="medium",
            tags="阅读,书单",
            completed_at=_at(days_ago(1), 21, 10),
        ),
        Task(
            title="写一页 Zotero 文献阅读笔记",
            description="选择本周最相关的一篇论文做结构化笔记",
            status="doing",
            priority="high",
            tags="科研,笔记",
            due_date=_at(current_day, 22),
        ),
        Task(
            title="阅读《构建第二大脑》第 4 章",
            status="todo",
            priority="medium",
            tags="阅读",
            due_date=_at(current_day, 23),
        ),
        Task(
            title="规划下周末短途旅行路线",
            status="todo",
            priority="low",
            tags="旅行",
            due_date=_at(current_day + timedelta(days=2), 20),
        ),
        Task(
            title="练习 MusicGen 生成 30 秒配乐",
            status="todo",
            priority="medium",
            tags="学习,音乐",
            due_date=_at(current_day + timedelta(days=1), 21),
        ),
    ]
    db.add_all(tasks)
    db.flush()
    ensure_tags(db, [tag for task in tasks for tag in normalize_tags(task.tags)])

    papers = [
        Paper(
            arxiv_id="2510.00001",
            title="Agentic Retrieval for Long-Horizon Scientific Discovery",
            authors="L. Chen, M. Torres, A. Nguyen",
            abstract=(
                "We present an agentic retrieval framework that decomposes long-horizon "
                "scientific questions into verifiable retrieval sub-tasks, improving "
                "evidence grounding for LLM research assistants."
            ),
            summary=(
                "提出面向长周期科研问题的新型 Agentic RAG 框架：将问题拆解为可验证的检索子任务，"
                "显著提升证据可追溯性，适合作为科研助手的检索层参考。"
            ),
            url="https://arxiv.org/abs/2510.00001",
            published_at=_at(current_day, 6),
            fetched_at=_at(current_day, 8, 5),
            tags="RAG,Agent,科研",
            published_date=current_day,
        ),
        Paper(
            arxiv_id="2510.00002",
            title="Audio Language Models as Controllable Music Producers",
            authors="S. Park, Y. Ito",
            abstract=(
                "A unified audio language model is fine-tuned for controllable music "
                "generation with textual and symbolic conditioning, enabling iterative "
                "production workflows."
            ),
            summary=(
                "统一音频语言模型，通过文本与符号双重条件实现可控音乐生成，"
                "支持迭代式制作流程，适合 AI 音乐学习中的进阶实践。"
            ),
            url="https://arxiv.org/abs/2510.00002",
            published_at=_at(current_day, 5),
            fetched_at=_at(current_day, 8, 5),
            tags="Audio,MusicGen,生成模型",
            published_date=current_day,
        ),
        Paper(
            arxiv_id="2510.00003",
            title="Video World Models with Sparse Memory Tokens",
            authors="R. Gupta, K. Müller",
            abstract=(
                "Sparse memory tokens reduce the compute cost of long video world models "
                "while preserving temporal consistency over thousands of frames."
            ),
            summary="稀疏记忆令牌降低长视频世界模型计算成本，在千帧级时序一致性上保持稳定。",
            url="https://arxiv.org/abs/2510.00003",
            published_at=_at(days_ago(1), 7),
            fetched_at=_at(days_ago(1), 8, 6),
            tags="Video,WorldModel",
            read_status="read",
            published_date=days_ago(1),
        ),
    ]
    db.add_all(papers)

    news = [
        NewsItem(
            source="Hugging Face Blog",
            title="Introducing a new open multimodal reasoning benchmark",
            link="https://huggingface.co/blog/demo-multimodal-benchmark",
            summary="新的多模态推理基准覆盖图文、视频与工具调用，强调可复现评测。",
            published_at=_at(current_day, 7),
            digest_date=current_day,
        ),
        NewsItem(
            source="Hacker News",
            title="Show HN: Local-first AI assistant toolkit",
            link="https://news.ycombinator.com/item?id=demo-local-ai",
            summary="本地优先的 AI 助手工具集，讨论个人知识库与隐私权衡。",
            published_at=_at(current_day, 6, 30),
            digest_date=current_day,
        ),
        NewsItem(
            source="arXiv cs.AI",
            title="Agentic Retrieval for Long-Horizon Scientific Discovery",
            link="https://arxiv.org/abs/2510.00001",
            summary="面向长周期科研任务的 Agentic RAG 框架。",
            published_at=_at(current_day, 6),
            digest_date=current_day,
        ),
        NewsItem(
            source="Hugging Face Blog",
            title="Fine-tuning audio models for personal music workflows",
            link="https://huggingface.co/blog/demo-audio-workflow",
            summary="个人音乐创作工作流中的音频模型微调实践。",
            published_at=_at(days_ago(1), 9),
            digest_date=days_ago(1),
        ),
    ]
    db.add_all(news)
    db.add(
        NewsDigest(
            digest_date=current_day,
            title=f"{current_day.month} 月 {current_day.day} 日 AI 前沿简报",
            content=(
                "今日关键词：Agentic RAG、多模态推理基准、本地优先 AI 工具。\n"
                "建议优先阅读 Agentic Retrieval，与本周科研目标直接相关。"
            ),
            item_count=3,
        )
    )

    video_track = LearningTrack(
        category="video",
        title="AI 视频学习路线",
        description="从扩散模型直觉到视频世界模型，按周拆解的小步学习路线。",
        progress=35,
    )
    music_track = LearningTrack(
        category="music",
        title="AI 音乐学习路线",
        description="从基础乐理到 MusicGen / ACE-Step 实操，最终完成个人作品。",
        progress=15,
    )
    db.add_all([video_track, music_track])
    db.flush()

    video_items = [
        LearningItem(
            track_id=video_track.id,
            title="扩散模型直觉：从噪声到图像",
            description="理解前向加噪与反向去噪的训练目标。",
            resource_url="https://www.bilibili.com/video/BV1demo001",
            status="done",
            mastery=80,
            scheduled_date=days_ago(1),
            completed_at=_at(days_ago(1), 20),
        ),
        LearningItem(
            track_id=video_track.id,
            title="视频生成基础：时空注意力",
            description="对比图像注意力与时空注意力的计算结构。",
            resource_url="https://www.youtube.com/watch?v=demo-video-02",
            status="todo",
            mastery=20,
            scheduled_date=current_day,
        ),
        LearningItem(
            track_id=video_track.id,
            title="动手复现：最小视频扩散模型",
            status="todo",
            mastery=0,
            scheduled_date=current_day + timedelta(days=1),
        ),
    ]
    music_items = [
        LearningItem(
            track_id=music_track.id,
            title="乐理速览：和弦进行与情绪",
            status="done",
            mastery=60,
            scheduled_date=days_ago(1),
            completed_at=_at(days_ago(1), 21),
        ),
        LearningItem(
            track_id=music_track.id,
            title="MusicGen 上手：文本条件生成",
            description="跑通官方示例并保存 3 段 15 秒片段。",
            resource_url="https://github.com/facebookresearch/audiocraft",
            status="todo",
            mastery=10,
            scheduled_date=current_day,
        ),
        LearningItem(
            track_id=music_track.id,
            title="为短片生成 30 秒配乐",
            status="todo",
            mastery=0,
            scheduled_date=current_day + timedelta(days=2),
        ),
    ]
    db.add_all(video_items + music_items)
    db.add_all(
        [
            LearningLog(
                track_id=video_track.id,
                content="已理解扩散模型的正向加噪过程，但反向过程还需要推导一遍。",
                mastery=60,
            ),
            LearningLog(
                track_id=music_track.id,
                content="和弦进行还需要更多练习，优先补齐大调与小调的区别。",
                mastery=40,
            ),
        ]
    )

    notes = [
        Book(
            title="构建第二大脑",
            author="Tiago Forte",
            status="reading",
            rating=4,
            notes="CODE 方法：捕获、组织、提炼、表达。",
            recommended_by="小红书收藏",
        ),
        Book(
            title="深度学习革命",
            author="Cade Metz",
            status="finished",
            rating=5,
            notes="了解 AI 发展脉络与关键人物。",
            recommended_by="AI 播客",
        ),
        Book(
            title="写作这回事",
            author="斯蒂芬·金",
            status="want",
            recommended_by="小红书收藏",
        ),
        Book(
            title="设计中的设计",
            author="原研哉",
            status="want",
            recommended_by="小红书收藏",
        ),
    ]
    db.add_all(notes)

    db.add_all(
        [
            Place(
                name="故宫博物院",
                country="中国",
                city="北京",
                lat=39.9163,
                lng=116.3972,
                visited=True,
                point_status="visited",
                point_category="景点",
                visit_date=date(2024, 5, 2),
                notes="清晨入馆人少，光影很好。",
            ),
            Place(
                name="外滩",
                country="中国",
                city="上海",
                lat=31.2400,
                lng=121.4906,
                visited=True,
                point_status="visited",
                point_category="景点",
                visit_date=date(2023, 10, 1),
            ),
            Place(
                name="清水寺",
                country="日本",
                city="京都",
                lat=34.9949,
                lng=135.7850,
                visited=True,
                point_status="visited",
                point_category="景点",
                visit_date=date(2024, 4, 5),
                notes="樱花季，建议早上 7 点前往。",
            ),
            Place(
                name="埃菲尔铁塔",
                country="法国",
                city="巴黎",
                lat=48.8584,
                lng=2.2945,
                visited=False,
                point_status="want",
                point_category="景点",
                notes="计划 2027 年春季前往。",
            ),
        ]
    )
    db.commit()
    logger.info("演示数据写入完成")
