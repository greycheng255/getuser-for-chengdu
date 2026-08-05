# -*- coding: utf-8 -*-
"""
对标文案提取服务

从竞品视频中提取口播文案：
视频链接 → yt-dlp 下载 → FFmpeg 提取音频 → faster-whisper 语音识别 → 清洗输出文案

对标超级IP智能体的"自动提取对标文案"功能。
"""
import asyncio
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any, Dict, List

logger = logging.getLogger("script_extractor")

# yt-dlp CLI 路径（系统安装，非 venv）
YT_DLP_BIN = "/home/ubuntu/.local/bin/yt-dlp"
FFMPEG_BIN = "/usr/bin/ffmpeg"
FFPROBE_BIN = "/usr/bin/ffprobe"

# 临时文件目录
TMP_DIR = "/tmp/talking_head"

# 外部视频解析服务（API.md 描述，已封装抖音/小红书/B站反爬和 ASR 识别）
PARSE_SERVICE_BASE_URL = "http://122.51.51.177:8002"
PARSE_SERVICE_TIMEOUT = 300  # 解析任务总超时（5分钟，长视频可能需要 2-3 分钟）
PARSE_SERVICE_POLL_INTERVAL = 5  # 进度轮询间隔（秒）


def _is_valid_video(path: str, require_audio: bool = True) -> bool:
    """用 ffprobe 检测文件是否包含有效的视频/音频流

    Playwright 拦截抖音视频时可能只捕获到分片数据或无音频流的预览版，
    导致 FFmpeg 提取音频报 "Output file does not contain any stream"。
    此函数在下载后立即验证，避免后续步骤无谓失败。

    Args:
        require_audio: True 时要求文件包含音频流（文案提取场景必须为 True）
    """
    try:
        result = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-show_entries",
             "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        streams = [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
        has_video = "video" in streams
        has_audio = "audio" in streams
        if not streams:
            logger.warning(
                f"[ScriptExtractor] 视频文件无效(无流): {path} "
                f"size={os.path.getsize(path)} bytes"
            )
            return False
        if require_audio and not has_audio:
            logger.warning(
                f"[ScriptExtractor] 视频文件无音频流(无法提取文案): {path} "
                f"size={os.path.getsize(path)} bytes streams={streams}"
            )
            return False
        return True
    except Exception as e:
        logger.warning(f"[ScriptExtractor] ffprobe 检测异常: {e}")
        return False


def _find_video_urls_in_json(obj: Any, depth: int = 0) -> list[str]:
    """递归搜索 JSON 对象中的视频 URL（优先 play_addr 压缩版，其次 download_addr）

    抖音 API 响应的 JSON 结构中，视频 URL 通常在:
    video.play_addr.url_list[0]（压缩版，适合文案提取）或
    video.download_addr.url_list[0]（高清版，文件太大不适合文案提取）

    过滤规则：
    - 排除 DASH 格式 URL（/play/dash/ 分离了音视频流，无法直接提取音频）
    - play_addr 优先于 download_addr（文件更小，下载更快）
    """
    if depth > 15 or not obj or not isinstance(obj, (dict, list)):
        return []
    play_urls: list[str] = []
    download_urls: list[str] = []
    if isinstance(obj, dict):
        for key in ("play_addr", "download_addr"):
            addr = obj.get(key)
            if isinstance(addr, dict):
                url_list = addr.get("url_list") or addr.get("urlList")
                if isinstance(url_list, list):
                    for u in url_list:
                        if not (isinstance(u, str) and u.startswith("http")):
                            continue
                        # 排除 DASH 格式（音视频分离，无法直接提取音频）
                        if "/play/dash/" in u:
                            continue
                        if key == "play_addr":
                            play_urls.append(u)
                        else:
                            download_urls.append(u)
        # 递归搜索子对象
        for v in obj.values():
            sub_play, sub_download = _find_video_urls_in_json_split(v, depth + 1)
            play_urls.extend(sub_play)
            download_urls.extend(sub_download)
    elif isinstance(obj, list):
        for item in obj:
            sub_play, sub_download = _find_video_urls_in_json_split(item, depth + 1)
            play_urls.extend(sub_play)
            download_urls.extend(sub_download)
    # play_addr 优先，download_addr 兜底
    return play_urls if play_urls else download_urls


def _find_video_urls_in_json_split(obj: Any, depth: int = 0) -> tuple[list[str], list[str]]:
    """_find_video_urls_in_json 的内部辅助，返回 (play_urls, download_urls)"""
    if depth > 15 or not obj or not isinstance(obj, (dict, list)):
        return [], []
    play_urls: list[str] = []
    download_urls: list[str] = []
    if isinstance(obj, dict):
        for key in ("play_addr", "download_addr"):
            addr = obj.get(key)
            if isinstance(addr, dict):
                url_list = addr.get("url_list") or addr.get("urlList")
                if isinstance(url_list, list):
                    for u in url_list:
                        if not (isinstance(u, str) and u.startswith("http")):
                            continue
                        if "/play/dash/" in u:
                            continue
                        if key == "play_addr":
                            play_urls.append(u)
                        else:
                            download_urls.append(u)
        for v in obj.values():
            sp, sd = _find_video_urls_in_json_split(v, depth + 1)
            play_urls.extend(sp)
            download_urls.extend(sd)
    elif isinstance(obj, list):
        for item in obj:
            sp, sd = _find_video_urls_in_json_split(item, depth + 1)
            play_urls.extend(sp)
            download_urls.extend(sd)
    return play_urls, download_urls


os.makedirs(TMP_DIR, exist_ok=True)


def _find_desc_in_json(obj: Any, depth: int = 0) -> str:
    """递归搜索抖音 API JSON 响应中的视频描述/字幕文本

    抖音 API 响应中，文案信息通常在以下字段：
    - aweme_detail.desc / desc_text（视频描述，用户发布时写的文案）
    - aweme_detail.caption（字幕）
    - aweme_detail.share_info.share_desc（分享描述）
    """
    if depth > 15 or not obj:
        return ""
    if isinstance(obj, dict):
        # 优先返回最长的文案字段
        candidates = []
        for key in ("desc", "desc_text", "caption", "share_desc"):
            val = obj.get(key)
            if isinstance(val, str) and len(val) > 5:
                candidates.append(val)
        if candidates:
            return max(candidates, key=len)
        # 递归搜索子对象
        for v in obj.values():
            result = _find_desc_in_json(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _find_desc_in_json(item, depth + 1)
            if result:
                return result
    return ""


def _extract_aweme_id(video_url: str) -> str:
    """从抖音 URL 中提取视频 ID（aweme_id）

    支持的 URL 格式：
    - https://www.douyin.com/video/{id}
    - https://www.douyin.com/jingxuan?modal_id={id}
    - https://www.douyin.com/discover?modal_id={id}
    - https://www.iesdouyin.com/share/video/{id}/
    - https://v.douyin.com/{short}/（短链，需先归一化）
    """
    import urllib.parse as up
    import re

    normalized = _normalize_url(video_url)
    parsed = up.urlparse(normalized)
    # /video/{id}
    m = re.search(r"/video/(\d+)", parsed.path)
    if m:
        return m.group(1)
    # /share/video/{id}/
    m = re.search(r"/share/video/(\d+)", parsed.path)
    if m:
        return m.group(1)
    # ?modal_id={id}
    q = up.parse_qs(parsed.query)
    modal_id = q.get("modal_id", [None])[0]
    if modal_id and modal_id.isdigit():
        return modal_id
    return ""


def _extract_api_description(video_url: str) -> str:
    """通过 Playwright 访问抖音分享页，直接从 SSR 数据提取文案文本（无需下载视频）

    抖音分享页 https://www.iesdouyin.com/share/video/{aweme_id}/ 反爬较弱，
    会将视频信息嵌入到 window._ROUTER_DATA 全局变量：
      _ROUTER_DATA.loaderData["video_(id)/page"].videoInfoRes.item_list[0].desc
    该 desc 即用户发布时填写的文案，对大多数口播视频即完整文案，
    无需再下载视频做语音识别。

    若分享页未拿到文案，回退到原 URL 拦截 API 响应 + SSR 数据兜底。

    Returns:
        文案文本；提取失败返回空字符串。
    """
    import json as _json
    import urllib.parse as up

    target_url = _normalize_url(video_url)
    # 仅支持抖音（其他平台 API 结构不同，走老路径）
    if "douyin.com" not in target_url:
        return ""

    aweme_id = _extract_aweme_id(video_url)
    # 分享页（反爬最弱，PC 端 /video/ 页面常因反爬导致视频详情 API 不被调用）
    share_url = f"https://www.iesdouyin.com/share/video/{aweme_id}/" if aweme_id else ""

    async def _extract():
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        try:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-software-rasterizer"],
            )
            # 用移动端 UA 访问分享页（更稳定，直接 SSR 渲染文案）
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
            )
            page = await context.new_page()

            best_desc = ""  # 记录最长的文案文本

            # ===== 步骤1：访问分享页，从 _ROUTER_DATA 提取文案 =====
            if share_url:
                try:
                    await page.goto(share_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(5)
                    # 优先从 window._ROUTER_DATA.loaderData[*].videoInfoRes.item_list[].desc 提取
                    ssr_desc = await page.evaluate("""
                        () => {
                            function findDesc(obj, depth) {
                                if (depth > 15 || !obj || typeof obj !== 'object') return '';
                                // 优先返回 videoInfoRes.item_list[].desc 或 aweme_detail.desc
                                const keys = ['desc', 'desc_text', 'caption', 'share_desc'];
                                let best = '';
                                for (const k of keys) {
                                    if (typeof obj[k] === 'string' && obj[k].length > 5 && obj[k].length > best.length) {
                                        best = obj[k];
                                    }
                                }
                                for (const key of Object.keys(obj)) {
                                    const r = findDesc(obj[key], depth + 1);
                                    if (r && r.length > best.length) best = r;
                                }
                                return best;
                            }
                            // 1. _ROUTER_DATA（分享页标准结构）
                            if (window._ROUTER_DATA) {
                                const d = findDesc(window._ROUTER_DATA, 0);
                                if (d) return d;
                            }
                            // 2. _SSR_DATA
                            if (window._SSR_DATA) {
                                const d = findDesc(window._SSR_DATA, 0);
                                if (d) return d;
                            }
                            // 3. __INIT_PROPS__
                            if (window.__INIT_PROPS__) {
                                const d = findDesc(window.__INIT_PROPS__, 0);
                                if (d) return d;
                            }
                            return '';
                        }
                    """)
                    if ssr_desc and len(ssr_desc) > len(best_desc):
                        best_desc = ssr_desc
                        logger.info(
                            f"[ScriptExtractor] 分享页SSR提取到文案: {len(ssr_desc)}字 from {share_url}"
                        )
                except Exception as e:
                    logger.warning(f"[ScriptExtractor] 分享页访问失败: {e}")

            # ===== 步骤2：分享页未拿到，回退到原 URL 拦截 API + SSR 兜底 =====
            if not best_desc:
                logger.info("[ScriptExtractor] 分享页未提取到文案，回退原URL拦截API响应")

                async def on_response(response):
                    nonlocal best_desc
                    url = response.url
                    ct = response.headers.get("content-type", "")
                    if "application/json" not in ct or "douyin.com" not in url:
                        return
                    try:
                        body = await response.body()
                        data = _json.loads(body)
                        # 必须包含 aweme_detail 或 videoInfoRes 字段才算视频详情
                        data_str = _json.dumps(data)[:5000]
                        if "aweme_detail" not in data_str and "videoInfoRes" not in data_str:
                            return
                        desc = _find_desc_in_json(data)
                        if desc and len(desc) > len(best_desc):
                            best_desc = desc
                            logger.info(
                                f"[ScriptExtractor] 从API响应提取到文案: {len(desc)}字 from {url[:80]}..."
                            )
                    except Exception:
                        pass

                page.on("response", on_response)
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(8)
                except Exception as e:
                    logger.warning(f"[ScriptExtractor] 原URL访问失败: {e}")

            return best_desc
        except Exception as e:
            logger.warning(f"[ScriptExtractor] API文案提取异常: {e}")
            return ""
        finally:
            await p.stop()

    try:
        return asyncio.run(_extract())
    except Exception as e:
        logger.warning(f"[ScriptExtractor] API文案提取失败: {e}")
        return ""


async def _extract_via_parse_service(video_url: str) -> Dict[str, Any] | None:
    """调用外部视频解析服务（http://122.51.51.177:8002）提取文案

    解析服务已封装抖音/小红书/B站的反爬和 ASR 识别（qwen_asr），
    返回完整字幕（含时间戳）、视频摘要、视频/音频 URL、作者信息等。
    优于本地 Playwright + Whisper 方案：
    - 有完整时间戳字幕（本地 Whisper base 模型识别质量较低）
    - 有视频摘要（summary.text + key_points）
    - 有可下载的视频/音频 URL
    - 不需要本地维护反爬逻辑

    流程：
        1. POST /api/v1/parse/tasks  创建解析任务
        2. GET  /api/v1/parse/tasks/{task_id}/progress  轮询进度
        3. GET  /api/v1/parse/tasks/{task_id}  获取完整结果

    Returns:
        成功：{raw_text, segments, duration, source_title, author,
              video_url, audio_url, summary_text, summary_key_points, thumbnail, task_id}
        失败：None
    """
    import httpx

    try:
        # 1. 创建解析任务
        async with httpx.AsyncClient(timeout=20.0) as client:
            create_resp = await client.post(
                f"{PARSE_SERVICE_BASE_URL}/api/v1/parse/tasks",
                json={
                    "url": video_url,
                    "options": {"generate_summary": True, "language": "zh-CN"},
                },
            )
            create_resp.raise_for_status()
            create_data = create_resp.json()
            if create_data.get("code") != 0:
                logger.warning(f"[ScriptExtractor] 解析服务创建任务失败: {create_data}")
                return None
            task_id = create_data["data"]["task_id"]
            logger.info(f"[ScriptExtractor] 解析服务任务已创建: {task_id} (url={video_url})")

        # 2. 轮询进度（每 5 秒一次，最长 5 分钟）
        deadline = time.time() + PARSE_SERVICE_TIMEOUT
        async with httpx.AsyncClient(timeout=10.0) as client:
            completed = False
            while time.time() < deadline:
                await asyncio.sleep(PARSE_SERVICE_POLL_INTERVAL)
                try:
                    prog_resp = await client.get(
                        f"{PARSE_SERVICE_BASE_URL}/api/v1/parse/tasks/{task_id}/progress"
                    )
                    prog_data = prog_resp.json()
                except Exception:
                    continue
                if prog_data.get("code") != 0:
                    continue
                status = prog_data["data"]["status"]
                progress = prog_data["data"].get("progress", 0)
                logger.info(f"[ScriptExtractor] 解析任务进度: {status} {progress}%")
                if status == "completed":
                    completed = True
                    break
                if status == "failed":
                    logger.warning(f"[ScriptExtractor] 解析任务失败: {prog_data}")
                    return None
            if not completed:
                logger.warning(
                    f"[ScriptExtractor] 解析任务超时(>{PARSE_SERVICE_TIMEOUT}s): {task_id}"
                )
                return None

        # 3. 获取完整结果
        async with httpx.AsyncClient(timeout=15.0) as client:
            result_resp = await client.get(
                f"{PARSE_SERVICE_BASE_URL}/api/v1/parse/tasks/{task_id}"
            )
            result_data = result_resp.json()
            if result_data.get("code") != 0:
                logger.warning(f"[ScriptExtractor] 解析服务获取结果失败: {result_data}")
                return None

        task_result = result_data.get("data") or {}
        source = task_result.get("source") or {}
        content = task_result.get("content") or {}
        summary = task_result.get("summary") or {}
        thumbnail = task_result.get("thumbnail") or {}

        # content.content = 字幕合并后的全文（视频描述 + ASR 字幕拼接）
        raw_text = content.get("content", "") or ""
        if not raw_text:
            logger.warning("[ScriptExtractor] 解析服务返回 content.content 为空")
            return None

        # 字幕列表 → segments 格式（与本地 whisper 输出一致）
        subtitles = content.get("subtitles") or []
        segments = [
            {
                "start": float(sub.get("start_time", 0) or 0),
                "end": float(sub.get("end_time", 0) or 0),
                "text": sub.get("content", "") or "",
            }
            for sub in subtitles
            if sub.get("content")
        ]

        result = {
            "raw_text": raw_text,
            "segments": segments,
            "duration": int(source.get("duration", 0) or 0),
            "source_title": source.get("title", "") or "",
            "author": source.get("author", "") or "",
            "video_url": content.get("video_url", "") or "",
            "audio_url": content.get("audio_url", "") or "",
            "summary_text": (summary.get("text", "") or "") if isinstance(summary, dict) else "",
            "summary_key_points": (summary.get("key_points", []) or []) if isinstance(summary, dict) else [],
            "thumbnail": (thumbnail.get("original", "") or thumbnail.get("medium", "") or "")
                         if isinstance(thumbnail, dict) else "",
            "task_id": task_id,
        }
        logger.info(
            f"[ScriptExtractor] 解析服务提取成功: "
            f"raw={len(raw_text)}字 segments={len(segments)} "
            f"duration={result['duration']}s author={result['author']}"
        )
        return result

    except Exception as e:
        logger.warning(f"[ScriptExtractor] 解析服务调用异常: {e}")
        return None


# whisper 模型单例（避免重复加载）
_whisper_model = None
_whisper_model_size = "base"  # tiny/base/small/medium/large，base 兼顾速度和准确率


def _get_whisper_model():
    """懒加载 faster-whisper 模型（首次调用时加载，约 500MB）"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        logger.info(f"[ScriptExtractor] 加载 faster-whisper 模型: {_whisper_model_size}")
        # 用 snapshot_download 解析模型路径（自动处理 HuggingFace 缓存）
        try:
            from huggingface_hub import snapshot_download
            model_path = snapshot_download(
                repo_id=f"Systran/faster-whisper-{_whisper_model_size}",
                allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.txt", "preprocessor_config.json"],
            )
            logger.info(f"[ScriptExtractor] 模型路径: {model_path}")
        except Exception as e:
            logger.warning(f"[ScriptExtractor] snapshot_download 失败，回退到模型名: {e}")
            model_path = _whisper_model_size
        _whisper_model = WhisperModel(
            model_path,
            device="cpu",
            compute_type="int8",  # CPU 上 int8 最快
        )
        logger.info("[ScriptExtractor] whisper 模型加载完成")
    return _whisper_model


def _download_video(video_url: str) -> str | None:
    """用 yt-dlp CLI 下载视频到临时目录，抖音失败时用 Playwright 兜底"""
    # URL 归一化：把各平台非标准 URL 转成 yt-dlp 能识别的格式
    video_url = _normalize_url(video_url)

    # 抖音用 Playwright 直接下载（yt-dlp 抖音提取器不稳定）
    if "douyin.com" in video_url:
        logger.info(f"[ScriptExtractor] 抖音视频，使用 Playwright 下载: {video_url}")
        result = _download_douyin_via_playwright(video_url)
        if result:
            return result
        logger.warning("[ScriptExtractor] Playwright 抖音下载失败，回退 yt-dlp")

    # 其他平台用 yt-dlp
    ts_prefix = str(int(time.time()))
    output_template = os.path.join(TMP_DIR, f"src_{ts_prefix}.%(ext)s")
    cmd = [
        YT_DLP_BIN,
        "--format", "mp4",
        "--output", output_template,
        "--quiet",
        "--no-warnings",
        "--no-playlist",
    ]

    # X/Twitter 有时也需要 cookies
    if "x.com" in video_url or "twitter.com" in video_url:
        cookies_file = _get_platform_cookies_file("x_twitter", video_url)
        if cookies_file:
            cmd.extend(["--cookies", cookies_file])

    # 抖音回退 yt-dlp 时必须有 fresh cookies（yt-dlp 抖音提取器要求）
    if "douyin.com" in video_url:
        cookies_file = _get_platform_cookies_file("douyin", video_url)
        if cookies_file:
            cmd.extend(["--cookies", cookies_file])
            logger.info("[ScriptExtractor] 抖音 yt-dlp 回退：已附加 fresh cookies")
        else:
            logger.warning("[ScriptExtractor] 抖音 yt-dlp 回退：未能获取 cookies，下载大概率会失败")

    cmd.append(video_url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            logger.warning(f"[ScriptExtractor] yt-dlp 失败: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        logger.warning("[ScriptExtractor] yt-dlp 下载超时(120s)")
        return None
    except Exception as e:
        logger.warning(f"[ScriptExtractor] yt-dlp 异常: {e}")
        return None

    # 查找下载的文件（用同一个时间戳前缀匹配）
    for fname in os.listdir(TMP_DIR):
        if fname.startswith(f"src_{ts_prefix}"):
            return os.path.join(TMP_DIR, fname)
    # fallback: 找最新的 mp4
    mp4_files = [f for f in os.listdir(TMP_DIR) if f.startswith("src_") and f.endswith(".mp4")]
    if mp4_files:
        mp4_files.sort(key=lambda f: os.path.getmtime(os.path.join(TMP_DIR, f)), reverse=True)
        return os.path.join(TMP_DIR, mp4_files[0])
    return None


def _download_douyin_via_playwright(video_url: str) -> str | None:
    """用 Playwright 访问抖音视频页，提取视频 URL 并下载

    抖音的 yt-dlp 提取器不稳定（需 cookies + 反爬严格），
    直接用 Playwright 在浏览器中加载页面，从 <video> 标签提取视频地址。
    """
    import asyncio
    import httpx

    ts_prefix = str(int(time.time()))
    output_path = os.path.join(TMP_DIR, f"src_{ts_prefix}.mp4")

    async def _download():
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        try:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-software-rasterizer"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            # 拦截视频响应和 API 响应，记录视频 URL
            captured_video_urls: list[tuple[str, int]] = []  # [(url, content_length), ...]
            api_video_urls: list[str] = []  # 从 API JSON 响应中提取的视频 URL

            async def on_response(response):
                url = response.url
                ct = response.headers.get("content-type", "")
                cl = int(response.headers.get("content-length", "0") or "0")
                # 排除特效素材（byteeffecttos.com / ies.fe.effect）——这些不是视频内容
                if "byteeffecttos.com" in url or "ies.fe.effect" in url:
                    return
                # 拦截抖音 API 响应（视频详情接口返回 JSON 包含 play_addr/download_addr）
                if "application/json" in ct and "douyin.com" in url:
                    try:
                        import json as _json
                        body = await response.body()
                        data = _json.loads(body)
                        urls = _find_video_urls_in_json(data)
                        for u in urls:
                            if u and u.startswith("http") and u not in api_video_urls:
                                api_video_urls.append(u)
                                logger.info(f"[ScriptExtractor] 从API响应提取视频URL: {u[:80]}...")
                    except Exception:
                        pass
                    return
                # 抖音视频的 URL 或 content-type 匹配
                if ("video/mp4" in ct or
                    "douyinvod" in url or "bytevcloudcdn" in url or "bytecdn" in url):
                    # 只记录较大的视频响应（>100KB 才可能是完整视频）
                    if cl > 100000 or cl == 0:
                        captured_video_urls.append((url, cl))
                        logger.info(f"[ScriptExtractor] 捕获视频URL: {cl} bytes from {url[:80]}...")

            page.on("response", on_response)

            # 访问视频页
            await page.goto(video_url, wait_until="domcontentloaded", timeout=30000)
            # 等待视频加载和播放（抖音视频会自动播放）
            await asyncio.sleep(12)

            # 合并候选视频 URL：API 响应提取的 URL（优先）+ 拦截到的视频 URL
            all_candidate_urls: list[str] = list(api_video_urls)
            for vurl, _ in captured_video_urls:
                if vurl not in all_candidate_urls:
                    all_candidate_urls.append(vurl)

            if all_candidate_urls:
                cookies = await context.cookies()
                cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                    for vurl in all_candidate_urls:
                        try:
                            resp = await client.get(
                                vurl,
                                headers={
                                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                                    "Referer": "https://www.douyin.com/",
                                    "Cookie": cookie_header,
                                },
                            )
                            if resp.status_code == 200 and len(resp.content) > 50000:
                                with open(output_path, "wb") as f:
                                    f.write(resp.content)
                                logger.info(f"[ScriptExtractor] 视频下载成功(httpx): {output_path} ({len(resp.content)} bytes) from {vurl[:60]}...")
                                if _is_valid_video(output_path):
                                    return output_path
                                logger.warning(f"[ScriptExtractor] httpx 下载的视频无效(无音频流)，尝试下一个 URL")
                                try:
                                    os.remove(output_path)
                                except OSError:
                                    pass
                        except Exception as e:
                            logger.warning(f"[ScriptExtractor] httpx 下载视频异常: {e}")
                logger.warning("[ScriptExtractor] 所有候选 video URL 均无效，尝试方法2/3")
            else:
                logger.warning("[ScriptExtractor] 未拦截到视频 URL 或 API 响应")

            # 方法2：从 <video> 标签提取 src（非 blob URL 的情况）
            video_src = await page.evaluate("""
                () => {
                    const video = document.querySelector('video');
                    if (video && video.src && !video.src.startsWith('blob:')) return video.src;
                    const source = document.querySelector('video source');
                    if (source && source.src && !source.src.startsWith('blob:')) return source.src;
                    return '';
                }
            """)

            # 方法3：从页面嵌入的 SSR/INIT 数据中提取视频 URL（抖音 PC 端将视频信息嵌入页面）
            if not video_src:
                video_src = await page.evaluate("""
                    () => {
                        // 递归搜索对象中的 play_addr / download_addr
                        function findVideoUrl(obj, depth) {
                            if (depth > 12 || !obj || typeof obj !== 'object') return null;
                            if (obj.play_addr && obj.play_addr.url_list && obj.play_addr.url_list.length > 0)
                                return obj.play_addr.url_list[0];
                            if (obj.download_addr && obj.download_addr.url_list && obj.download_addr.url_list.length > 0)
                                return obj.download_addr.url_list[0];
                            for (const key of Object.keys(obj)) {
                                const r = findVideoUrl(obj[key], depth + 1);
                                if (r) return r;
                            }
                            return null;
                        }
                        // 尝试多个全局变量
                        for (const src of [window._SSR_DATA, window.__INIT_PROPS__]) {
                            if (src) {
                                const url = findVideoUrl(src, 0);
                                if (url) return url;
                            }
                        }
                        // 尝试从 RENDER_DATA script 标签提取（URL 编码的 JSON）
                        const rd = document.getElementById('RENDER_DATA');
                        if (rd && rd.textContent) {
                            try {
                                const data = JSON.parse(decodeURIComponent(rd.textContent));
                                const url = findVideoUrl(data, 0);
                                if (url) return url;
                            } catch(e) {}
                        }
                        return '';
                    }
                """)
                if video_src:
                    logger.info(f"[ScriptExtractor] 从页面 SSR 数据提取到视频URL: {video_src[:80]}...")

            if video_src and video_src.startswith("http"):
                cookies = await context.cookies()
                cookie_header = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
                async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
                    resp = await client.get(
                        video_src,
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Referer": "https://www.douyin.com/",
                            "Cookie": cookie_header,
                        },
                    )
                    if resp.status_code == 200 and len(resp.content) > 10000:
                        with open(output_path, "wb") as f:
                            f.write(resp.content)
                        logger.info(f"[ScriptExtractor] 视频下载成功: {output_path} ({len(resp.content)} bytes)")
                        if _is_valid_video(output_path):
                            return output_path
                        logger.warning("[ScriptExtractor] 方法2/3下载的视频无效(无音频流)，回退 yt-dlp")
                        try:
                            os.remove(output_path)
                        except OSError:
                            pass

            logger.warning("[ScriptExtractor] Playwright 未捕获到有效视频数据")
            return None

        except Exception as e:
            logger.warning(f"[ScriptExtractor] Playwright 抖音下载异常: {e}")
            return None
        finally:
            await p.stop()

    try:
        return asyncio.run(_download())
    except Exception as e:
        logger.warning(f"[ScriptExtractor] Playwright 抖音下载失败: {e}")
        return None


def _normalize_url(url: str) -> str:
    """URL 归一化：把各平台非标准 URL 转成 yt-dlp 能识别的格式

    处理的场景：
    - 抖音 jingxuan?modal_id=xxx → /video/xxx
    - 抖音 discover?modal_id=xxx → /video/xxx
    - 抖音 note/xxx → /video/xxx（图文帖可能无视频，但仍尝试）
    - 小红书 xhslink.com 短链 → 跟随重定向取真实URL
    - B站 b23.tv 短链 → 跟随重定向取真实URL
    """
    import urllib.parse as up

    parsed = up.urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path
    query = up.parse_qs(parsed.query)

    # ===== 抖音 URL 归一化 =====
    if "douyin.com" in host:
        # jingxuan?modal_id=xxx / discover?modal_id=xxx / search?modal_id=xxx
        modal_id = query.get("modal_id", [None])[0]
        if modal_id and "/video/" not in path:
            new_url = f"https://www.douyin.com/video/{modal_id}"
            logger.info(f"[ScriptExtractor] URL归一化: {url} → {new_url}")
            return new_url
        # iesdouyin.com 短链 / v.douyin.com 短链 → 原样（yt-dlp 原生支持）

    # ===== 小红书短链 =====
    if "xhslink.com" in host:
        # 短链需要跟随重定向，yt-dlp 原生支持跟随
        return url

    # ===== B站短链 =====
    if "b23.tv" in host:
        return url

    # ===== X/Twitter =====
    if "x.com" in host or "twitter.com" in host:
        return url  # yt-dlp 原生支持

    return url


def _get_platform_cookies_file(platform: str, video_url: str = "") -> str | None:
    """从数据库查平台 cookies，生成 yt-dlp 用的 Netscape 格式 cookies 文件

    yt-dlp 的 --cookies 参数需要 Netscape 格式的 cookies 文件
    """
    import asyncio
    import os
    import time

    cookies_path = os.path.join(TMP_DIR, f"cookies_{platform}_{int(time.time())}.txt")

    try:
        import asyncpg
        import os as _os
        from dotenv import load_dotenv
        load_dotenv()

        async def _fetch_cookies():
            conn = await asyncpg.connect(
                host=_os.getenv("DB_HOST"),
                port=int(_os.getenv("DB_PORT", "15435")),
                database=_os.getenv("DB_NAME"),
                user=_os.getenv("DB_USER"),
                password=_os.getenv("DB_PASSWORD"),
                timeout=10,
            )
            try:
                row = await conn.fetchrow(
                    "SELECT cookies FROM publisher_accounts WHERE platform=$1 AND is_active=1 AND status!='banned' ORDER BY updated_at DESC LIMIT 1",
                    platform,
                )
                return row["cookies"] if row else None
            finally:
                await conn.close()

        cookies_str = asyncio.run(_fetch_cookies())
        if not cookies_str:
            logger.info(f"[ScriptExtractor] 数据库无 {platform} cookies，尝试 Playwright 生成")
            # 降级：用 Playwright 访问视频页获取 fresh cookies
            cookies_str = _generate_fresh_cookies_via_playwright(platform, video_url)
            if not cookies_str:
                return None

        # 解析 cookie 字符串 → Netscape 格式
        # cookie 字符串格式: "key1=val1; key2=val2; ..."
        # Netscape 格式: domain<TAB>flag<TAB>path<TAB>secure<TAB>expiration<TAB>name<TAB>value
        domain_map = {
            "douyin": ".douyin.com",
            "x_twitter": ".x.com",
        }
        domain = domain_map.get(platform, f".{platform}.com")

        lines = ["# Netscape HTTP Cookie File", "# This is generated by script_extractor"]
        for pair in cookies_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                name = name.strip()
                value = value.strip()
                # domain, flag, path, secure, expiration, name, value
                lines.append(f"{domain}\tTRUE\t/\tFALSE\t0\t{name}\t{value}")

        with open(cookies_path, "w") as f:
            f.write("\n".join(lines) + "\n")

        logger.info(f"[ScriptExtractor] 生成 {platform} cookies 文件: {cookies_path} ({len(lines)-2} cookies)")
        return cookies_path

    except Exception as e:
        logger.warning(f"[ScriptExtractor] 获取 {platform} cookies 失败: {e}")
        return None


def _generate_fresh_cookies_via_playwright(platform: str, video_url: str = "") -> str | None:
    """用 Playwright 访问平台页面，获取 fresh cookies（无需登录）

    抖音要求 "Fresh cookies (not necessarily logged in)"，
    需要访问视频页面本身（而非仅首页）才能获得有效 cookies。
    """
    import asyncio

    # 如果有视频URL，直接访问视频页；否则访问首页
    if video_url:
        target_url = _normalize_url(video_url)
    else:
        target_url = {
            "douyin": "https://www.douyin.com/",
            "x_twitter": "https://x.com/",
        }.get(platform)
    if not target_url:
        return None

    async def _get_cookies():
        from playwright.async_api import async_playwright
        p = await async_playwright().start()
        try:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--disable-software-rasterizer"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            # 访问目标页面
            await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
            # 等待 JS 写入 cookies
            await asyncio.sleep(5)
            cookies = await context.cookies()
            # 拼接成 "key=val; key=val" 格式
            cookie_pairs = [f"{c['name']}={c['value']}" for c in cookies]
            return "; ".join(cookie_pairs)
        except Exception as e:
            logger.warning(f"[ScriptExtractor] Playwright 获取 {platform} cookies 失败: {e}")
            return None
        finally:
            await p.stop()

    try:
        cookies_str = asyncio.run(_get_cookies())
        if cookies_str:
            logger.info(f"[ScriptExtractor] Playwright 生成 {platform} fresh cookies: {len(cookies_str)} chars (from {target_url[:60]})")
        return cookies_str
    except Exception as e:
        logger.warning(f"[ScriptExtractor] Playwright fresh cookies 异常: {e}")
        return None


def _extract_audio(video_path: str) -> str | None:
    """用 FFmpeg 从视频中提取 16kHz mono wav 音频（whisper 要求）"""
    audio_path = video_path.rsplit(".", 1)[0] + ".wav"
    cmd = [
        FFMPEG_BIN,
        "-i", video_path,
        "-ar", "16000",   # 16kHz
        "-ac", "1",       # 单声道
        "-c:a", "pcm_s16le",
        "-y",
        "-hide_banner", "-loglevel", "error",
        audio_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.warning(f"[ScriptExtractor] FFmpeg 提取音频失败: {result.stderr[:200]}")
            return None
    except Exception as e:
        logger.warning(f"[ScriptExtractor] FFmpeg 异常: {e}")
        return None
    return audio_path if os.path.exists(audio_path) else None


def _transcribe(audio_path: str) -> Dict[str, Any]:
    """用 faster-whisper 识别音频，返回文本和分段时间戳"""
    model = _get_whisper_model()
    try:
        # language="zh" 强制中文识别；beam_size=5 兼顾速度和准确率
        segments_iter, info = model.transcribe(
            audio_path,
            language="zh",
            beam_size=5,
            vad_filter=True,        # 过滤静音段
            vad_parameters={"min_silence_duration_ms": 500},
        )
        segments: List[Dict[str, Any]] = []
        raw_text_parts: List[str] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if text:
                segments.append({
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": text,
                })
                raw_text_parts.append(text)
        raw_text = "".join(raw_text_parts)
        duration = round(info.duration, 2) if info else 0
        return {
            "raw_text": raw_text,
            "segments": segments,
            "duration": duration,
            "language": info.language if info else "zh",
        }
    except Exception as e:
        logger.error(f"[ScriptExtractor] whisper 识别失败: {e}")
        return {"raw_text": "", "segments": [], "duration": 0, "language": "zh"}


# 口语清洗：去掉常见语气词、重复词
_FILLER_WORDS = re.compile(
    r"(?:嗯|啊|呢|嘛|哈|哎|哦|呃|那个|这个|就是说|然后呢|对吧|你知道吗|对不对|是不是)+[，,。！？\s]*"
)
_REPEATED_CHARS = re.compile(r"(.)\1{2,}")  # 连续3个以上相同字符


def _clean_text(raw: str) -> str:
    """清洗口播文案：去语气词、去重复、合并断句"""
    if not raw:
        return ""
    text = _FILLER_WORDS.sub("", raw)
    text = _REPEATED_CHARS.sub(r"\1", text)
    # 合并多余空格
    text = re.sub(r"\s+", "", text)
    # 按句号/问号/感叹号分段
    sentences = re.split(r"([。！？!?])", text)
    cleaned_parts = []
    for i in range(0, len(sentences) - 1, 2):
        s = sentences[i] + (sentences[i + 1] if i + 1 < len(sentences) else "")
        s = s.strip()
        if s:
            cleaned_parts.append(s)
    if not cleaned_parts and text.strip():
        cleaned_parts = [text.strip()]
    return "\n".join(cleaned_parts)


async def extract_script(video_url: str, platform: str = "") -> Dict[str, Any]:
    """从视频链接提取口播文案

    提取策略（优先级从高到低）：
    1. 外部解析服务：调用 http://122.51.51.177:8002 解析服务，获取完整字幕+摘要+视频URL
       （推荐，最稳定；已封装抖音/小红书/B站反爬和 qwen_asr 字幕识别）
    2. API 文本提取：拦截平台 API 响应/分享页 SSR 直接取文案文本（兜底，无需下载视频）
    3. 视频下载 → 音频提取 → 语音识别：最后兜底，处理纯口播无文字描述的视频

    Args:
        video_url: 视频链接（X/抖音/小红书/B站等）
        platform: 平台标识（可选，用于日志）

    Returns:
        {raw_text, cleaned_text, segments, duration, video_url, platform, extraction_method, ...}
        extraction_method: "parse_service" | "api" | "speech_recognition"
        解析服务成功时额外返回：source_title, author, parsed_video_url, audio_url,
                              summary_text, summary_key_points, thumbnail, parse_task_id
    """
    logger.info(f"[ScriptExtractor] 开始提取文案: {video_url} (platform={platform})")

    # ===== 1. 优先调用外部解析服务（最完整：含字幕、摘要、视频URL）=====
    try:
        parse_result = await _extract_via_parse_service(video_url)
        if parse_result and parse_result.get("raw_text"):
            raw_text = parse_result["raw_text"]
            cleaned = _clean_text(raw_text)
            logger.info(
                f"[ScriptExtractor] 解析服务提取成功: "
                f"raw={len(raw_text)}字 cleaned={len(cleaned)}字 "
                f"segments={len(parse_result.get('segments', []))}"
            )
            return {
                "raw_text": raw_text,
                "cleaned_text": cleaned,
                "segments": parse_result.get("segments", []),
                "duration": parse_result.get("duration", 0),
                "video_url": video_url,
                "platform": platform,
                "extraction_method": "parse_service",
                # 解析服务额外返回的字段（供前端展示与后续仿写使用）
                "source_title": parse_result.get("source_title", ""),
                "author": parse_result.get("author", ""),
                "parsed_video_url": parse_result.get("video_url", ""),
                "audio_url": parse_result.get("audio_url", ""),
                "summary_text": parse_result.get("summary_text", ""),
                "summary_key_points": parse_result.get("summary_key_points", []),
                "thumbnail": parse_result.get("thumbnail", ""),
                "parse_task_id": parse_result.get("task_id", ""),
            }
        logger.info("[ScriptExtractor] 解析服务未返回文案，降级到API文本提取")
    except Exception as e:
        logger.warning(f"[ScriptExtractor] 解析服务调用异常，降级: {e}")

    # ===== 2. API 文本提取（兜底，无需下载视频）=====
    try:
        api_desc = await asyncio.to_thread(_extract_api_description, video_url)
        if api_desc and len(api_desc) > 10:
            cleaned = _clean_text(api_desc)
            logger.info(
                f"[ScriptExtractor] API文案提取成功: "
                f"raw={len(api_desc)}字 cleaned={len(cleaned)}字"
            )
            return {
                "raw_text": api_desc,
                "cleaned_text": cleaned,
                "segments": [],
                "duration": 0,
                "video_url": video_url,
                "platform": platform,
                "extraction_method": "api",
            }
        logger.info(
            "[ScriptExtractor] API 未提取到文案(或文案过短)，降级到视频下载+语音识别"
        )
    except Exception as e:
        logger.warning(f"[ScriptExtractor] API 文案提取异常，降级到视频下载: {e}")

    # ===== 3. 最后兜底：下载视频 → 提取音频 → 语音识别 =====
    video_path = await asyncio.to_thread(_download_video, video_url)
    if not video_path:
        raise RuntimeError(f"视频下载失败: {video_url}")

    try:
        # 3. 提取音频
        audio_path = await asyncio.to_thread(_extract_audio, video_path)
        if not audio_path:
            raise RuntimeError("音频提取失败")

        try:
            # 4. 语音识别
            result = await asyncio.to_thread(_transcribe, audio_path)

            # 5. 清洗文案
            cleaned = _clean_text(result["raw_text"])

            logger.info(
                f"[ScriptExtractor] 提取完成(语音识别): "
                f"raw={len(result['raw_text'])}字 cleaned={len(cleaned)}字 "
                f"segments={len(result['segments'])} duration={result['duration']}s"
            )

            return {
                "raw_text": result["raw_text"],
                "cleaned_text": cleaned,
                "segments": result["segments"],
                "duration": result["duration"],
                "video_url": video_url,
                "platform": platform,
                "extraction_method": "speech_recognition",
            }
        finally:
            # 清理音频临时文件
            try:
                os.remove(audio_path)
            except OSError:
                pass
    finally:
        # 清理视频临时文件
        try:
            os.remove(video_path)
        except OSError:
            pass


async def extract_script_from_audio(audio_path: str) -> Dict[str, Any]:
    """直接从音频文件提取文案（用于声音克隆样本验证等场景）"""
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"音频文件不存在: {audio_path}")

    result = await asyncio.to_thread(_transcribe, audio_path)
    cleaned = _clean_text(result["raw_text"])
    return {
        "raw_text": result["raw_text"],
        "cleaned_text": cleaned,
        "segments": result["segments"],
        "duration": result["duration"],
    }
