import argparse
import os
import json
import sys
from urllib.parse import urlparse, parse_qs
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from src.config import settings
from src.providers.youtube import YouTubeProvider
from src.providers.bilibili import BilibiliProvider
from src.services.summarizer import SummarizerService
from src.utils.logger import logger
from src.utils.cookies import ensure_cookies_file

console = Console()

def format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"

def to_markdown(metadata, summary) -> str:
    lines = []
    lines.append(f"# {metadata.title}")
    lines.append(f"\n> 作者：{metadata.author}\n")
    lines.append("## 一句话总结")
    lines.append(summary.one_sentence_summary)
    lines.append("\n## 关键要点")
    for kp in summary.key_points:
        lines.append(f"- {kp}")
    lines.append("\n## 章节")
    for chapter in summary.chapters:
        lines.append(f"### {chapter.title} （{format_time(chapter.start_time)} - {format_time(chapter.end_time)}）")
        for p in chapter.summary:
            lines.append(f"- {p}")
        if getattr(chapter, 'keyframes', None):
            lines.append("\n#### 关键帧")
            for kf in chapter.keyframes:
                if getattr(kf, 'image_path', None):
                    lines.append(f"![{chapter.title}]({kf.image_path})")
                lines.append(f"- 时间：{format_time(int(kf.timestamp))}，说明：{kf.description}")
        lines.append("")
    if getattr(summary, 'quotes', None):
        lines.append("## 金句")
        for q in summary.quotes:
            lines.append(f"- {q.text} （{format_time(int(q.timestamp))}）")
    return "\n".join(lines)

def render_summary(metadata, summary):
    # Header
    console.print(Panel(f"[bold blue]{metadata.title}[/bold blue]\n[italic]{metadata.author}[/italic]", title="Video Info"))
    
    # One Sentence
    console.print(Panel(summary.one_sentence_summary, title="One Sentence Summary", border_style="green"))
    
    # Key Points
    kp_md = "\n".join([f"- {kp}" for kp in summary.key_points])
    console.print(Panel(Markdown(kp_md), title="Key Points", border_style="yellow"))
    
    # Chapters
    table = Table(title="Chapters", show_header=True, header_style="bold magenta")
    table.add_column("Time", style="cyan", width=15)
    table.add_column("Chapter", style="white")
    
    for chapter in summary.chapters:
        time_range = f"{format_time(chapter.start_time)} - {format_time(chapter.end_time)}"
        content = f"[bold]{chapter.title}[/bold]\n" + "\n".join([f"• {p}" for p in chapter.summary])
        
        if chapter.keyframes:
            kf_info = "\n\n[dim]Keyframes:[/dim]\n"
            for kf in chapter.keyframes:
                kf_info += f"- {kf.image_path}\n"
            content += kf_info
            
        table.add_row(time_range, content)
        table.add_section()
        
    console.print(table)

def main():
    parser = argparse.ArgumentParser(description="AI Video Summarizer")
    # 支持位置参数与可选 --url，两者任选其一
    parser.add_argument("url", nargs="?", help="Video URL (YouTube or Bilibili)")
    parser.add_argument("--url", dest="url", help="Video URL (YouTube or Bilibili)")
    parser.add_argument("--lang", help="Output language (zh/en)", default="zh")
    parser.add_argument("--cookies", help="Path to cookies.txt")
    parser.add_argument("--no-save", action="store_true", help="Do not save output to file (default: saves to outputs/)")
    parser.add_argument("--model", help="LLM Model to use")
    parser.add_argument("--use-whisper", action="store_true", help="Enable Whisper ASR fallback for videos without subtitles")
    parser.add_argument("--keyframes", action="store_true", help="Extract keyframes for each chapter")
    parser.add_argument("--no-cache", action="store_true", help="Disable summary cache and recompute")
    parser.add_argument("--extractive", action="store_true", help="Generate extractive study notes without LLM")
    # 新增视觉标志
    parser.add_argument("--vision", action="store_true", help="Refine summary using keyframe images (multimodal)")
    
    args = parser.parse_args()

    # 必须提供 URL
    if not getattr(args, "url", None):
        parser.print_help()
        console.print("[red]Missing URL.[/red] Provide positional URL or --url.")
        sys.exit(2)

    args.url = args.url.strip().strip('`').strip('"').strip("'").strip()
    try:
        p = urlparse(args.url)
        if "youtube.com" in (p.netloc or "") and p.path == "/watch":
            qs = parse_qs(p.query or "")
            v = (qs.get("v") or [None])[0]
            if v:
                args.url = f"https://www.youtube.com/watch?v={v}"
        elif "youtu.be" in (p.netloc or ""):
            vid = (p.path or "").strip("/").split("/")[0]
            if vid:
                args.url = f"https://www.youtube.com/watch?v={vid}"
    except Exception:
        pass
    
    # Default behavior: Save unless --no-save is passed
    should_save = not args.no_save

    
    # Override settings
    if args.lang:
        settings.OUTPUT_LANG = args.lang
    if args.model:
        settings.LLM_MODEL = args.model

    # Normalize URL if it's a raw Bilibili BV ID
    if args.url.startswith("BV") and "bilibili.com" not in args.url:
        args.url = f"https://www.bilibili.com/video/{args.url}"
        console.print(f"[dim]Detected BV ID, normalizing to: {args.url}[/dim]")

    # Determine Provider
    if "bilibili" in args.url or "BV" in args.url:
        platform = "bilibili"
        provider = BilibiliProvider()
    else:
        platform = "youtube"
        provider = YouTubeProvider()

    service = SummarizerService()

    # Determine cookies path (CLI arg > Env var > Generated from Env)
    cookies_path = args.cookies or settings.COOKIES_PATH
    if not cookies_path:
        cookies_path = ensure_cookies_file(platform)

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=True
        ) as progress:
            
            # Step 1: Info & Transcript
            task1 = progress.add_task(description="Fetching video info & transcript...", total=None)
            metadata = provider.extract_info(args.url, cookies_path=cookies_path)
            transcript = provider.get_transcript(args.url, allow_asr=args.use_whisper, cookies_path=cookies_path)
            progress.update(task1, completed=True)
            console.print(f"[green]✔[/green] Found video: [bold]{metadata.title}[/bold] ({len(transcript.segments)} segments)")

            # Step 2: Summarize
            task2 = progress.add_task(description="Summarizing content (Map-Reduce)...", total=None)
            summary = service.summarize(
                transcript, 
                metadata, 
                extract_keyframes=(args.keyframes or args.vision),
                cookies_path=cookies_path,
                force_refresh=args.no_cache,
                use_vision=args.vision
            )
            progress.update(task2, completed=True)

            # Step 3: Study Notes
            task3 = progress.add_task(description="Generating study notes...", total=None)
            study_md = service.generate_study_notes(transcript, metadata, summary)
            progress.update(task3, completed=True)
            if args.extractive:
                task4 = progress.add_task(description="Generating extractive notes...", total=None)
                study_extractive_md = service.generate_extractive_notes(transcript, metadata)
                progress.update(task4, completed=True)

        # Render
        render_summary(metadata, summary)

        # Save
        if should_save:
            output_dir = os.path.join(settings.OUTPUT_DIR, metadata.id)
            os.makedirs(output_dir, exist_ok=True)
            
            # Save JSON
            with open(os.path.join(output_dir, "summary.json"), "w", encoding="utf-8") as f:
                f.write(summary.model_dump_json(indent=2))
            
            # Save Transcript
            with open(os.path.join(output_dir, "transcript.json"), "w", encoding="utf-8") as f:
                f.write(transcript.model_dump_json(indent=2))
            
            # Save Markdown
            md_text = to_markdown(metadata, summary)
            with open(os.path.join(output_dir, "summary.md"), "w", encoding="utf-8") as f:
                f.write(md_text)
            
            # Save Study Notes
            with open(os.path.join(output_dir, "study.md"), "w", encoding="utf-8") as f:
                f.write(study_md)
            if args.extractive:
                with open(os.path.join(output_dir, "study_extractive.md"), "w", encoding="utf-8") as f:
                    f.write(study_extractive_md)
            
            console.print(f"\n[blue]Saved output to {output_dir}[/blue]")

    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        # logger.exception(e) # Uncomment for debug

if __name__ == "__main__":
    main()
