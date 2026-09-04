import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pathlib import Path

from app.media_downloader.api.media_router import get_media_extractor_service, router
from app.media_downloader.core.detector import detect_platform, normalize_share_url
from app.media_downloader.core.extractor import MEDIA_PARSE_CACHE_NAMESPACE
from app.media_downloader.core.streamer import MediaPreviewStreamer
from app.media_downloader.platforms.douyin import DouyinExtractor
from app.media_downloader.platforms.xiaohongshu import XHSExtractor
from app.media_downloader.schemas.media import MediaInfo


def test_detect_platform_extracts_douyin_url_from_share_text():
    detection = detect_platform(
        "5.87 复制打开抖音，看看这个作品 https://v.douyin.com/demo/ 解析"
    )

    assert detection.platform == "douyin"
    assert detection.normalized_url == "https://v.douyin.com/demo/"


def test_normalize_share_url_rejects_text_without_url():
    with pytest.raises(ValueError, match="未找到有效"):
        normalize_share_url("解析一下")


def test_media_parse_cache_namespace_invalidates_old_parser_results():
    assert MEDIA_PARSE_CACHE_NAMESPACE == "media-v6"


def test_media_parse_route_returns_preview_payload():
    class FakeService:
        async def parse(self, url: str):
            assert url == "https://v.douyin.com/demo/"
            return MediaInfo(
                platform="douyin",
                type="video",
                title="城市夜景",
                author="摄影师",
                cover="https://example.com/cover.jpg",
                video_url="https://example.com/video.mp4",
            )

        def parse_id_for(self, url: str) -> str:
            return "parse-123"

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_media_extractor_service] = lambda: FakeService()
    client = TestClient(app)

    response = client.post("/media/parse", json={"url": "https://v.douyin.com/demo/"})

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "data": {
            "platform": "douyin",
            "type": "video",
            "title": "城市夜景",
            "author": "摄影师",
            "cover": "https://example.com/cover.jpg",
            "video_url": "https://example.com/video.mp4",
            "images": [],
            "duration": None,
            "create_time": None,
            "download_url": "https://example.com/video.mp4",
            "raw": {},
            "parse_id": "parse-123",
            "preview_url": "/media/preview/parse-123",
            "image_preview_urls": [],
            "can_download": True,
        },
    }


def test_media_parse_route_returns_proxied_image_payload():
    class FakeService:
        async def parse(self, url: str):
            return MediaInfo(
                platform="xiaohongshu",
                type="images",
                title="花莲的海",
                images=[
                    "http://sns-webpic-qc.xhscdn.com/a!nd_dft_wlteh_jpg_3",
                    "http://sns-webpic-qc.xhscdn.com/b!nd_dft_wlteh_jpg_3",
                ],
            )

        def parse_id_for(self, url: str) -> str:
            return "parse-images"

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_media_extractor_service] = lambda: FakeService()
    client = TestClient(app)

    response = client.post("/media/parse", json={"url": "https://xhslink.cn/demo"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["images"] == [
        "http://sns-webpic-qc.xhscdn.com/a!nd_dft_wlteh_jpg_3",
        "http://sns-webpic-qc.xhscdn.com/b!nd_dft_wlteh_jpg_3",
    ]
    assert data["image_preview_urls"] == [
        "/media/image/parse-images/0",
        "/media/image/parse-images/1",
    ]


def test_xhs_html_fallback_ignores_non_xhs_image_assets():
    html = """
    <html>
      <img src="https://example.com/route-overview.png">
      <img src="https://cdn.example.com/book.webp">
    </html>
    """

    with pytest.raises(ValueError, match="未在小红书页面中找到笔记媒体数据"):
        XHSExtractor.parse_page_html(html)


def test_xhs_html_fallback_accepts_xhs_note_images_only():
    html = """
    <html>
      <img src="https://example.com/route-overview.png">
      <img src="https://sns-webpic-qc.xhscdn.com/202609041420/target-a!nd_dft_wlteh_jpg_3">
      <img src="https://sns-webpic-qc.xhscdn.com/202609041420/target-b!nd_dft_wlteh_jpg_3">
    </html>
    """

    info = XHSExtractor.parse_page_html(html)

    assert info.type == "images"
    assert info.images == [
        "https://sns-webpic-qc.xhscdn.com/202609041420/target-a!nd_dft_wlteh_jpg_3",
        "https://sns-webpic-qc.xhscdn.com/202609041420/target-b!nd_dft_wlteh_jpg_3",
    ]


def test_douyin_image_post_takes_priority_over_video_field():
    payload = {
        "aweme_detail": {
            "desc": "douyin image post",
            "author": {"nickname": "album author"},
            "video": {
                "play_addr": {"url_list": ["https://example.com/not-target.mp4"]},
            },
            "image_post_info": {
                "images": [
                    {"display_image": {"url_list": ["https://example.com/image-1.jpeg"]}},
                    {"origin_image": {"url_list": ["https://example.com/image-2.webp"]}},
                ]
            },
        }
    }

    info = DouyinExtractor.parse_aweme_detail(payload)

    assert info.type == "images"
    assert info.video_url == ""
    assert info.images == [
        "https://example.com/image-1.jpeg",
        "https://example.com/image-2.webp",
    ]


def test_douyin_image_post_uses_one_best_url_per_image_item():
    payload = {
        "aweme_detail": {
            "desc": "dedupe",
            "author": {"nickname": "author"},
            "image_post_info": {
                "images": [
                    {
                        "display_image": {
                            "url_list": [
                                "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-a~tplv-dy-aweme-images:q75.webp?x=1",
                                "https://p9-pc-sign.douyinpic.com/tos-cn-i/item-a~tplv-dy-aweme-images:q75.webp?x=2",
                                "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-a~tplv-dy-aweme-images:q75.jpeg?x=3",
                            ]
                        },
                        "owner_watermark_image": {
                            "url_list": [
                                "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-a~tplv-dy-water-v2.webp?x=4"
                            ]
                        },
                    },
                    {
                        "display_image": {
                            "url_list": [
                                "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-b~tplv-dy-aweme-images:q75.webp?x=5",
                                "https://p9-pc-sign.douyinpic.com/tos-cn-i/item-b~tplv-dy-aweme-images:q75.webp?x=6",
                            ]
                        }
                    },
                ]
            },
        }
    }

    info = DouyinExtractor.parse_aweme_detail(payload)

    assert info.images == [
        "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-a~tplv-dy-aweme-images:q75.webp?x=1",
        "https://p3-pc-sign.douyinpic.com/tos-cn-i/item-b~tplv-dy-aweme-images:q75.webp?x=5",
    ]


@pytest.mark.anyio
async def test_preview_streamer_keeps_downloaded_mp4_when_transcode_fails(tmp_path):
    async def fake_fetcher(url: str, path: Path, max_bytes: int, headers):
        path.write_bytes(b"\x00\x00\x00 ftypisom\x00\x00\x02\x00demo-video")
        return "video/mp4"

    async def failing_transcoder(source: Path, target: Path):
        raise RuntimeError("ffmpeg unavailable")

    info = MediaInfo(
        platform="xiaohongshu",
        type="video",
        video_url="https://example.com/video.mp4",
    )
    streamer = MediaPreviewStreamer(
        tmp_path,
        fetcher=fake_fetcher,
        transcoder=failing_transcoder,
    )
    target = streamer.path_for("parse-123", info.video_url)

    await streamer.materialize(info.video_url, target, info)

    assert target.exists()
    assert target.read_bytes().startswith(b"\x00\x00\x00 ftypisom")
