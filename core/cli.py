"""CLI argument parsing for the YouTube Shorts Pipeline."""

from __future__ import annotations

import argparse
from typing import List


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Analytical YouTube Shorts Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python main.py https://youtube.com/watch?v=xxx\n"
            "  python main.py --url https://youtube.com/watch?v=xxx --upload\n"
            "  python main.py --resume short_20260618_123456/clip_1\n"
        ),
    )
    parser.add_argument("url", nargs="?", help="YouTube video URL for Phase 1")
    parser.add_argument("--resume", help="Resume Phase 2 from clip path (e.g. short_XXX/clip_1)")
    parser.add_argument("--format", default="format1", help="Format config name (default: format1)")
    parser.add_argument("--content-type", default="general", choices=["general", "football"],
                        help="Content type for specialized framing (default: general)")
    parser.add_argument("--legacy-select", action="store_true",
                        help="Revert clip selection to old preview-only listing (default: rich full-text)")
    parser.add_argument("--auto-reframe", action="store_true",
                        help="Subject-aware 9:16 crop (face tracking) instead of centre crop")
    parser.add_argument("--framing", default="crop", choices=["crop", "fit"],
                        help="9:16 framing: 'crop' (default) or 'fit' (full frame on blurred fill, keeps full-width subtitles)")
    parser.add_argument("--upload", action="store_true", help="Upload final video to YouTube")
    parser.add_argument("--schedule", type=int, default=-1, help="Schedule upload N days from now")
    parser.add_argument("--no-captions", action="store_true", help="Skip caption overlay")
    parser.add_argument("--karaoke", action="store_true",
                        help="Per-word karaoke caption highlighting (animated)")
    parser.add_argument("--trim-silence", action="store_true",
                        help="Cut silent gaps from source before transcription (tighter pacing)")
    parser.add_argument("--translate", action="store_true", help="Translate captions (es->en)")
    parser.add_argument("--intro", help="Path to intro audio (default: search clip dir)")
    parser.add_argument("--gpu", action="store_true", default=True, help="Enable GPU acceleration")
    parser.add_argument("--no-gpu", action="store_false", dest="gpu", help="Disable GPU acceleration")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")
    parser.add_argument("--memory-report", action="store_true",
                        help="Print memory store summary and exit")
    parser.add_argument("--memory-dry-run", action="store_true",
                        help="Run memory write-back in dry-run mode (no save)")
    parser.add_argument("--memory-compact", action="store_true",
                        help="Dedup and prune old memory entries")
    parser.add_argument("--fetch-analytics", action="store_true",
                        help="Fetch YouTube stats for uploaded videos and score performance")
    parser.add_argument("--propose-weights", action="store_true",
                        help="SIMULATION: propose scoring-dimension weights from performance feedback (not applied)")
    parser.add_argument("--mode", default="observation_only",
                        choices=["observation_only", "adaptive_mode"],
                        help="Memory influence mode (default: observation_only)")
    parser.add_argument("--trace-arbiter", action="store_true",
                        help="Print full arbitration decision chain")
    return parser.parse_args(argv)
