"""Shared SellerSprite review workbook schema and date formatting."""

import datetime as dt

REVIEW_COLS = [
    "ASIN",
    "标题",
    "标题(翻译)",
    "内容",
    "内容(翻译)",
    "VP评论",
    "Vine Voice评论",
    "型号",
    "星级",
    "赞同数",
    "图片数量",
    "图片地址",
    "是否有视频",
    "视频地址",
    "评论链接",
    "评论人",
    "头像地址",
    "所属国家",
    "评论人主页",
    "红人计划链接",
    "评论时间",
]


def ms_to_date(v) -> str:
    if not v:
        return ""
    try:
        return dt.datetime.utcfromtimestamp(int(v) / 1000).strftime("%Y-%m-%d")
    except (ValueError, TypeError, OSError):
        return ""
