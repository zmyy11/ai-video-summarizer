import os
import subprocess
from typing import List, Optional
from src.config import settings
from src.utils.logger import logger

class KeyFrameExtractor:
    def __init__(self):
        self.output_dir = os.path.join(settings.OUTPUT_DIR, "keyframes")
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_keyframe(self, video_path: str, timestamp: float, video_id: str) -> Optional[str]:
        try:
            output_filename = f"{video_id}_{int(timestamp)}.jpg"
            output_path = os.path.join(self.output_dir, output_filename)
            if os.path.exists(output_path):
                return output_path
            cmd = [
                "ffmpeg",
                "-ss", str(timestamp),
                "-i", video_path,
                "-vframes", "1",
                "-q:v", "2",
                "-y",
                output_path
            ]
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            return output_path
        except Exception as e:
            logger.error(f"Failed to extract keyframe at {timestamp}s: {e}")
            return None

    def extract_batch(self, video_url: str, timestamps: List[float], video_id: str, cookies_path: Optional[str] = None) -> List[str]:
        try:
            import yt_dlp
            # First: try to get a direct progressive stream URL
            probe_opts = {'quiet': True, 'format': 'best', 'no_warnings': True}
            if cookies_path:
                probe_opts['cookiefile'] = cookies_path
            stream_url = None
            with yt_dlp.YoutubeDL(probe_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                fmts = info.get('formats') or []
                progressive = [
                    f for f in fmts
                    if (f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('url'))
                ]
                # Prefer highest height/tbr regardless of ext
                progressive.sort(key=lambda f: (-(f.get('height') or 0), -(f.get('tbr') or 0)))
                if progressive:
                    stream_url = progressive[0].get('url')
                else:
                    stream_url = info.get('url')
            results = []
            if stream_url:
                for ts in timestamps:
                    path = self.extract_keyframe(stream_url, ts, video_id)
                    if path:
                        results.append(path)
                if results:
                    return results
            # Fallback: download locally with broad format selection
            logger.info(f"Direct stream extraction failed, downloading video locally...")
            outtmpl = os.path.join(settings.CACHE_DIR, f"{video_id}.%(ext)s")
            # For Bilibili: use workaround format to avoid format errors
            # Select best video and best audio separately, let yt-dlp merge
            dl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
                'merge_output_format': 'mp4',
                'outtmpl': outtmpl,
                'quiet': False,  # Show warnings to debug
                'no_warnings': False,
                'ignoreerrors': True,  # Continue on errors
            }
            if cookies_path:
                dl_opts['cookiefile'] = cookies_path

            # Try to download
            try:
                with yt_dlp.YoutubeDL(dl_opts) as ydl:
                    ydl.download([video_url])
            except Exception as download_error:
                logger.warning(f"Download with merge failed: {download_error}, trying simplified format...")
                # Try even simpler: just get best video only (no audio needed for keyframes)
                dl_opts['format'] = 'bestvideo/best'
                try:
                    with yt_dlp.YoutubeDL(dl_opts) as ydl:
                        ydl.download([video_url])
                except Exception as e2:
                    logger.error(f"All download attempts failed: {e2}")
                    return []

            local_file = None
            preferred = None
            for name in os.listdir(settings.CACHE_DIR):
                if name.startswith(f"{video_id}."):
                    path = os.path.join(settings.CACHE_DIR, name)
                    # Prefer mp4/mkv/webm in that order, otherwise accept any
                    if name.endswith('.mp4'):
                        preferred = path
                        break
                    if name.endswith('.mkv'):
                        preferred = preferred or path
                    if name.endswith('.webm'):
                        preferred = preferred or path
                    local_file = local_file or path
            local_file = preferred or local_file
            if not local_file:
                logger.error(f"No video file found after download for {video_id}")
                return []

            logger.info(f"Extracting keyframes from local file: {local_file}")
            results = []
            for ts in timestamps:
                path = self.extract_keyframe(local_file, ts, video_id)
                if path:
                    results.append(path)
            return results
        except Exception as e:
            logger.error(f"Batch keyframe extraction failed: {e}")
            return []

keyframe_extractor = KeyFrameExtractor()
