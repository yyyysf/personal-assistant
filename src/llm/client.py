"""DeepSeek V4-Flash（OpenAI 兼容）客户端。未配置 Key 时明确报错，由上层降级。"""

from functools import lru_cache
from urllib.parse import urlparse

from openai import OpenAI

from src.core.config import settings
from src.core.logging import get_logger

logger = get_logger(__name__)


class LLMNotConfigured(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


@lru_cache
def _client() -> OpenAI:
    if not settings.llm_configured:
        raise LLMNotConfigured("未配置 DEEPSEEK_API_KEY，已使用本地降级内容")
    base_url = settings.deepseek_base_url or "https://api.deepseek.com"
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise LLMNotConfigured("DEEPSEEK_BASE_URL 配置不合法")
    return OpenAI(
        api_key=settings.deepseek_api_key,
        base_url=base_url,
        timeout=60.0,
        max_retries=2,
    )


def chat(
    prompt: str,
    system: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 1500,
) -> str:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = _client().chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        return content.strip()
    except LLMNotConfigured:
        raise
    except Exception as exc:  # 网络/鉴权/模型等外部错误统一包装
        logger.warning("LLM 调用失败：%s", exc)
        raise LLMError(f"LLM 调用失败：{exc}") from exc
