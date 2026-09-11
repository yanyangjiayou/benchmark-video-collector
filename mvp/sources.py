from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse


def normalize_creator_url(value: str, platform: str, *, allow_short: bool = True) -> str:
    """Accept a homepage URL or the URL embedded in a platform share message."""
    text = value.strip()
    match = re.search(r"https?://[^\s<>\"'，。；、）)]+", text)
    if match:
        text = match.group(0)
    elif platform == "dy" and text.startswith("MS4w"):
        text = f"https://www.douyin.com/user/{text}"
    elif platform == "xhs" and re.fullmatch(r"[0-9a-fA-F]{24}", text):
        text = f"https://www.xiaohongshu.com/user/profile/{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise ValueError("请粘贴博主主页链接，可直接粘贴分享文字；不要填写昵称或抖音号")
    if platform == "dy":
        if host not in {"douyin.com", "www.douyin.com", "v.douyin.com", "www.iesdouyin.com", "iesdouyin.com"}:
            raise ValueError("当前平台是抖音，请填写抖音博主主页链接")
        if host == "v.douyin.com" and allow_short:
            return text
        creator_id = parse_qs(parsed.query).get("sec_uid", [""])[0]
        path_match = re.fullmatch(r"/(?:share/)?user/([^/]+)/?", parsed.path)
        creator_id = creator_id or (path_match.group(1) if path_match else "")
        if not creator_id or not creator_id.startswith("MS4w"):
            raise ValueError("请使用抖音博主主页链接（douyin.com/user/…），视频链接和抖音号不能用于主页采集")
        return f"https://www.douyin.com/user/{creator_id}"
    if host not in {"xiaohongshu.com", "www.xiaohongshu.com", "xhslink.cn", "xhslink.com"}:
        raise ValueError("当前平台是小红书，请填写小红书博主主页链接")
    if host in {"xhslink.cn", "xhslink.com"} and allow_short:
        return text
    if not re.fullmatch(r"/user/profile/[^/]+/?", parsed.path):
        raise ValueError("请使用小红书博主主页链接，笔记链接不能用于主页采集")
    return text
