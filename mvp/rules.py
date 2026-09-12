from __future__ import annotations

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from .sources import normalize_creator_url


class CollectionRequest(BaseModel):
    platform: Literal["xhs", "dy"]
    trigger_type: Literal["creator_url", "keyword"]
    creator_url: str = ""
    keywords: list[str] = Field(default_factory=list)
    min_followers: int | None = Field(default=None, ge=0)
    start_date: date | None = None
    end_date: date | None = None
    min_likes: int = Field(default=200, ge=0)
    max_items: int = Field(default=10, ge=1, le=50)
    video_only: bool = True
    transcribe_video: bool = True

    @model_validator(mode="after")
    def complete_and_validate(self) -> "CollectionRequest":
        today = date.today()
        if self.end_date is None:
            self.end_date = today
        if self.start_date is None:
            self.start_date = self.end_date - timedelta(days=29)
        if self.start_date > self.end_date:
            raise ValueError("开始日期不能晚于结束日期")
        if self.trigger_type == "creator_url" and not self.creator_url.strip():
            raise ValueError("指定博主模式必须填写主页链接")
        if self.trigger_type == "creator_url":
            self.creator_url = normalize_creator_url(self.creator_url, self.platform)
        if self.trigger_type == "keyword" and not any(k.strip() for k in self.keywords):
            raise ValueError("关键词模式必须至少填写一个关键词")
        return self

    def confirmation(self) -> dict[str, object]:
        return {
            "平台": "小红书" if self.platform == "xhs" else "抖音",
            "入口": "指定博主" if self.trigger_type == "creator_url" else "关键词发现",
            "开始日期": self.start_date.isoformat(),
            "结束日期": self.end_date.isoformat(),
            "最低点赞": self.min_likes,
            "最低粉丝": self.min_followers if self.min_followers is not None else "不限制",
            "最多条数": self.max_items,
            "仅视频": self.video_only,
            "本地转写": self.transcribe_video,
        }
