import os
import re
import json
import inspect
import html
import xml.etree.ElementTree as ET
import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from typing import Optional, Dict, Any
from src.core.video import VideoSource
from src.models.video import VideoMetadata
from src.models.transcript import Transcript, Segment
from src.utils.logger import logger
from src.config import settings
from src.utils.cookies import load_netscape_cookies_as_dict

class YouTubeProvider(VideoSource):
    def _get_video_id(self, url: str) -> str:
        m = re.search(r"(?:v=|/shorts/)([A-Za-z0-9_-]{11})", url)
        if m:
            return m.group(1)
        m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
        if m:
            return m.group(1)
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                return info['id']
        except Exception as e:
            logger.error(f"Failed to extract ID: {e}")
            raise

    def extract_info(self, url: str, cookies_path: Optional[str] = None) -> VideoMetadata:
        opts = {'quiet': True}
        if cookies_path:
            opts['cookiefile'] = cookies_path
            
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return VideoMetadata(
                id=info['id'],
                title=info['title'],
                author=info.get('uploader', 'Unknown'),
                duration=info.get('duration', 0),
                platform='youtube',
                url=info['webpage_url'],
                description=info.get('description'),
                thumbnail_url=info.get('thumbnail')
            )

    def get_transcript(self, url: str, allow_asr: bool = False, cookies_path: Optional[str] = None) -> Transcript:
        video_id = self._get_video_id(url)
        cookies = load_netscape_cookies_as_dict(cookies_path, "youtube.com") if cookies_path else {}
        
        # Method 1: youtube-transcript-api (Best for structured data)
        try:
            logger.info("Attempting to fetch transcript via youtube-transcript-api...")
            lang_prefs = ['zh-Hans', 'zh-Hant', 'zh-CN', 'zh-TW', 'zh-HK', 'zh', 'en']

            transcript_list = None
            if hasattr(YouTubeTranscriptApi, "list_transcripts"):
                list_sig = inspect.signature(YouTubeTranscriptApi.list_transcripts)
                if cookies and "cookies" in list_sig.parameters:
                    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id, cookies=cookies)
                else:
                    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            else:
                api = YouTubeTranscriptApi()
                if hasattr(api, "list"):
                    transcript_list = api.list(video_id)

            if transcript_list is None:
                raise AttributeError("youtube-transcript-api has no supported transcript listing method")

            if hasattr(transcript_list, "find_manually_created_transcript"):
                try:
                    transcript = transcript_list.find_manually_created_transcript(lang_prefs)
                except Exception:
                    try:
                        transcript = transcript_list.find_generated_transcript(lang_prefs)
                    except Exception:
                        try:
                            transcript = transcript_list.find_transcript(lang_prefs)
                        except Exception:
                            transcript = None
                            manual = getattr(transcript_list, "_manually_created_transcripts", None)
                            generated = getattr(transcript_list, "_generated_transcripts", None)
                            for group in (manual, generated):
                                if isinstance(group, dict) and group:
                                    for code, tr in group.items():
                                        if "zh" in (code or "").lower():
                                            transcript = tr
                                            break
                                    if transcript is None:
                                        transcript = next(iter(group.values()))
                                if transcript is not None:
                                    break

                if transcript is None:
                    raise NoTranscriptFound(video_id, lang_prefs, transcript_list)

                if transcript.language_code != 'zh-Hans' and transcript.is_translatable:
                    try:
                        transcript = transcript.translate('zh-Hans')
                    except Exception:
                        pass

                data = transcript.fetch()
                segments = []
                for item in data:
                    if isinstance(item, dict):
                        start = item.get("start")
                        duration = item.get("duration")
                        text = item.get("text")
                    else:
                        start = getattr(item, "start", None)
                        duration = getattr(item, "duration", None)
                        text = getattr(item, "text", None)
                    if start is None or duration is None or text is None:
                        continue
                    segments.append(Segment(start=float(start), end=float(start) + float(duration), text=str(text)))
                return Transcript(video_id=video_id, language=transcript.language_code, segments=segments)

            if hasattr(YouTubeTranscriptApi, "get_transcript"):
                get_sig = inspect.signature(YouTubeTranscriptApi.get_transcript)
                if cookies and "cookies" in get_sig.parameters:
                    data = YouTubeTranscriptApi.get_transcript(video_id, languages=lang_prefs, cookies=cookies)
                else:
                    data = YouTubeTranscriptApi.get_transcript(video_id, languages=lang_prefs)
                segments = [Segment(start=item['start'], end=item['start'] + item['duration'], text=item['text']) for item in data]
                return Transcript(video_id=video_id, language="auto", segments=segments)
            raise AttributeError("youtube-transcript-api has no supported get_transcript method")
            
        except (TranscriptsDisabled, NoTranscriptFound) as e:
            logger.warning(f"youtube-transcript-api failed: {e}. Trying yt-dlp...")
        except Exception as e:
            logger.error(f"Unexpected error in youtube-transcript-api: {e}")

        # Method 2: yt-dlp subtitles (Fallback)
        try:
            opts = {
                'quiet': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'skip_download': True,
            }
            if cookies_path:
                opts['cookiefile'] = cookies_path
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            subs = info.get('subtitles') or info.get('automatic_captions') or {}
            if not subs:
                raise ValueError("No subtitles found via yt-dlp.")
            candidates = []
            for lang, items in subs.items():
                items_list = items if isinstance(items, list) else [items]
                for it in items_list:
                    if isinstance(it, dict) and it.get('url'):
                        ext = (it.get('ext') or '').lower()
                        candidates.append((lang, it['url'], ext))
            if not candidates:
                raise ValueError("Could not extract subtitle URL from yt-dlp subtitle metadata.")
            lang_prefs = ['zh-Hans', 'zh-Hant', 'zh', 'en']
            fmt_prefs = ['vtt', 'srt', 'json3', 'srv3']
            def lang_rank(l: str) -> int:
                l2 = (l or '').lower()
                for i, p in enumerate(lang_prefs):
                    if p.lower() == l2:
                        return i
                if 'zh' in l2:
                    return 0
                if 'en' in l2:
                    return 10
                return 99
            def fmt_rank(f: str) -> int:
                f2 = (f or '').lower()
                for i, p in enumerate(fmt_prefs):
                    if p == f2:
                        return i
                return 99
            candidates.sort(key=lambda x: (lang_rank(x[0]), fmt_rank(x[2])))
            selected_lang, sub_url, fmt = candidates[0]
            headers = {
                'Referer': 'https://www.youtube.com',
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get(sub_url, headers=headers, cookies=cookies or None, timeout=30)
            resp.raise_for_status()
            text = resp.text
            segments = []
            if fmt == 'vtt' or text.lstrip().startswith('WEBVTT'):
                segments = self._parse_vtt(text)
            elif fmt == 'srt' or '-->' in text:
                segments = self._parse_srt(text)
            else:
                segments = self._parse_json3(text)
                if not segments:
                    segments = self._parse_srv3(text)
            if not segments:
                raise ValueError("Failed to parse subtitles via yt-dlp fallback.")
            return Transcript(video_id=video_id, language=selected_lang, segments=segments)
        except Exception as e:
            logger.warning(f"yt-dlp subtitle fallback failed: {e}")

        if allow_asr:
            logger.info("Falling back to Whisper ASR for YouTube...")
            return self._transcribe_with_whisper(url, cookies_path)

        raise ValueError("Could not find a valid transcript. Enable ASR with --use-whisper.")

    def _parse_vtt(self, content: str):
        lines = [l.rstrip('\n') for l in content.splitlines()]
        segments = []
        time_re = re.compile(r"(?P<start>\d{2}:\d{2}(?::\d{2})?[\.,]\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}(?::\d{2})?[\.,]\d{3})")

        def ts_to_sec(ts: str) -> float:
            ts = ts.replace(',', '.')
            parts = ts.split(':')
            if len(parts) == 2:
                h = 0
                m, s = parts
            else:
                h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            m = time_re.search(line)
            if not m:
                continue
            start = ts_to_sec(m.group('start'))
            end = ts_to_sec(m.group('end'))
            text_lines = []
            while i < len(lines) and lines[i].strip() != '':
                if '-->' in lines[i]:
                    break
                text_lines.append(lines[i].strip())
                i += 1
            while i < len(lines) and lines[i].strip() == '':
                i += 1
            text = ' '.join([t for t in text_lines if t])
            if text:
                segments.append(Segment(start=start, end=end, text=text))
        return segments

    def _parse_json3(self, content: str):
        try:
            data: Dict[str, Any] = json.loads(content)
        except Exception:
            return []
        events = data.get("events") or []
        segments = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            start_ms = ev.get("tStartMs")
            dur_ms = ev.get("dDurationMs")
            if start_ms is None or dur_ms is None:
                continue
            segs = ev.get("segs") or []
            if not isinstance(segs, list):
                continue
            text = "".join([(s.get("utf8") or "") for s in segs if isinstance(s, dict)]).replace("\n", " ").strip()
            if not text:
                continue
            start = float(start_ms) / 1000.0
            end = (float(start_ms) + float(dur_ms)) / 1000.0
            segments.append(Segment(start=start, end=end, text=text))
        return segments

    def _parse_srv3(self, content: str):
        txt = content.lstrip()
        if not txt.startswith("<"):
            return []
        try:
            root = ET.fromstring(content)
        except Exception:
            return []
        segments = []
        for node in root.iter():
            if node.tag.split("}")[-1] != "text":
                continue
            start_s = node.attrib.get("start") or node.attrib.get("t")
            dur_s = node.attrib.get("dur") or node.attrib.get("d")
            if start_s is None or dur_s is None:
                continue
            try:
                start = float(start_s)
                end = start + float(dur_s)
            except Exception:
                continue
            text = html.unescape("".join(node.itertext())).replace("\n", " ").strip()
            if text:
                segments.append(Segment(start=start, end=end, text=text))
        return segments

    def _parse_srt(self, content: str):
        segments = []
        blocks = re.split(r"\n\s*\n", content.strip(), flags=re.MULTILINE)

        def ts_to_sec(ts: str) -> float:
            ts = ts.replace(',', '.')
            h, m, s = ts.split(':')
            return int(h) * 3600 + int(m) * 60 + float(s)

        for block in blocks:
            lines = [l.strip() for l in block.splitlines() if l.strip()]
            if not lines:
                continue
            idx = 0
            if re.match(r"^\d+$", lines[0]):
                idx = 1
            if idx >= len(lines) or '-->' not in lines[idx]:
                continue
            try:
                start_s, end_s = [t.strip() for t in lines[idx].split('-->')]
                start = ts_to_sec(start_s)
                end = ts_to_sec(end_s)
            except Exception:
                continue
            text = ' '.join(lines[idx + 1:]).strip()
            if text:
                segments.append(Segment(start=start, end=end, text=text))
        return segments

    def _transcribe_with_whisper(self, url: str, cookies_path: Optional[str] = None) -> Transcript:
        try:
            import whisper
        except ImportError:
            raise ImportError("openai-whisper is not installed. Run `uv add openai-whisper`.")
        video_id = self._get_video_id(url)
        audio_path = os.path.join(settings.CACHE_DIR, f"{video_id}.mp3")
        if not os.path.exists(audio_path):
            os.makedirs(settings.CACHE_DIR, exist_ok=True)
            logger.info("Downloading audio for ASR...")
            opts = {
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'outtmpl': os.path.join(settings.CACHE_DIR, f"{video_id}.%(ext)s"),
                'quiet': True,
            }
            if cookies_path:
                opts['cookiefile'] = cookies_path
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        logger.info("Transcribing audio with Whisper (this may take a while)...")
        model = whisper.load_model("base")
        result = model.transcribe(audio_path)
        segments = [Segment(start=seg['start'], end=seg['end'], text=seg['text'].strip()) for seg in result.get('segments', [])]
        return Transcript(video_id=video_id, language=result.get('language', 'unknown'), source="asr_whisper", segments=segments)
