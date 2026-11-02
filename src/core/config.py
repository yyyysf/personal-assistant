"""应用配置：所有密钥只从环境变量 / .env 读取，禁止硬编码。"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "My Private Assistant"
    app_env: str = "local"
    debug: bool = True
    host: str = "127.0.0.1"
    port: int = 8000
    timezone: str = "Asia/Shanghai"

    database_url: str = "sqlite:///./data/assistant.db"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    zotero_api_key: str = ""
    zotero_user_id: str = ""
    zotero_library_type: str = "user"
    zotero_local_api_url: str = "http://127.0.0.1:23119/api"

    enable_scheduler: bool = True
    arxiv_fetch_hour: int = 8
    arxiv_fetch_minute: int = 5
    rss_fetch_hour: int = 8
    rss_fetch_minute: int = 40
    arxiv_categories: str = "cs.AI"
    arxiv_max_results: int = 20
    rss_feeds: str = (
        "https://arxiv.org/rss/cs.AI,"
        "https://huggingface.co/blog/feed.xml,"
        "https://hnrss.org/frontpage"
    )

    mcp_mode: str = "stdio"
    seed_demo_data: bool = True

    mcp_config_path: Path = Field(default=BASE_DIR / "src" / "mcp_host" / "servers.json")

    @property
    def llm_configured(self) -> bool:
        return bool(self.deepseek_api_key.strip())

    @property
    def zotero_configured(self) -> bool:
        return bool(self.zotero_api_key.strip() and self.zotero_user_id.strip())

    @property
    def rss_feed_list(self) -> list[str]:
        return [item.strip() for item in self.rss_feeds.split(",") if item.strip()]

    @property
    def arxiv_category_list(self) -> list[str]:
        return [item.strip() for item in self.arxiv_categories.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
