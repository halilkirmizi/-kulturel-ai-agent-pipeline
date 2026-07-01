#!/usr/bin/env python3
"""YouTube Shorts Pipeline — main orchestrator.

Thin entry point. All logic lives in core/phase1, core/phase2, core/upload, core/cli.
This file only wires them together.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure pipeline root is on sys.path for module imports
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from core.artifact_registry import AOR, ArtifactRecord
from core.config import build_config
from core.logger import get_logger, setup_logging
from core.memory_writer import MemoryWriter
from core.steptracker import StepTracker
from core.feature_registry import registry
from core.cli import parse_args
from core.phase1 import run_phase1, PipelineError
from core.phase2 import run_phase2
from core.upload import run_upload


log = get_logger(__name__)


# ── Feature declaration ────────────────────────────────────────
registry.declare("step_tracker", "core", "Execution step gating with persistence")


# ── AOR declarations ─────────────────────────────────────────
AOR.declare(ArtifactRecord(name="source_video", path_pattern="temp/<id>.mp4", owner="ingest.downloader", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="transcript_segments", path_pattern="memory", owner="core.phase1", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="topics", path_pattern="memory", owner="core.phase1", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="scored_clips", path_pattern="memory", owner="core.phase1", lifecycle="ephemeral"))
AOR.declare(ArtifactRecord(name="cropped_clip", path_pattern="shorts_output/.../clip.mp4", owner="core.phase1", lifecycle="derived", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="state_json", path_pattern="shorts_output/.../state.json", owner="core.phase1", lifecycle="persistent", source_of_truth=True))
AOR.declare(ArtifactRecord(name="enhanced_intro", path_pattern="temp/intro_enhanced_<hash>.mp3", owner="core.phase2", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="captions_ass", path_pattern="shorts_output/.../captions.ass", owner="core.phase2", lifecycle="derived", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="captioned_video", path_pattern="temp/captioned_<hash>.mp4", owner="core.phase2", lifecycle="ephemeral", delete_policy="end_of_run"))
AOR.declare(ArtifactRecord(name="final_video", path_pattern="shorts_output/.../final.mp4", owner="core.phase2", lifecycle="persistent", delete_policy="after_upload"))
AOR.declare(ArtifactRecord(name="execution_trace", path_pattern="execution_trace.json", owner="core.steptracker", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="upload_log", path_pattern="upload/.upload_log.json", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="upload_quota", path_pattern="upload/.upload_quota.json", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="graph_store", path_pattern="obsidian_bridge/graph_store.json", owner="obsidian_bridge.build_graph", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="format_config", path_pattern="formats/format1.json", owner="core.config", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="oauth_token", path_pattern="~/.youtube_upload_token.pickle", owner="upload.youtube", lifecycle="persistent"))
AOR.declare(ArtifactRecord(name="client_secret", path_pattern="upload/client_secret.json", owner="upload.youtube", lifecycle="persistent"))
AOR.freeze()


def _run_memory_writer(
    tracker: StepTracker,
    aor_path: Path,
    root_dir: Path,
    dry_run: bool = False,
) -> None:
    """Collect signals and run memory write-back."""
    mw = MemoryWriter(root_dir)
    summary = mw.run(
        execution_trace_path=tracker._path,
        aor_state_path=aor_path,
        dry_run=dry_run,
    )
    if summary["promoted"] > 0:
        log.info("Memory: %d new entries (dry_run=%s)", summary["promoted"], dry_run)


def main(argv=None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    args = parse_args(argv)

    # Setup logging
    setup_logging(level=args.log_level)
    log.info("Pipeline starting (format=%s, gpu=%s, upload=%s)", args.format, args.gpu, args.upload)

    # Build config
    config = build_config(
        format_name=args.format,
        content_type=args.content_type,
        legacy_select=args.legacy_select,
        select_provider=args.select_with,
        apply_weights=args.apply_weights,
        framing=args.framing,
        auto_reframe=args.auto_reframe,
        gpu=args.gpu,
        upload=args.upload,
        schedule_days=args.schedule,
        no_captions=args.no_captions,
        karaoke=args.karaoke,
        trim_silence=args.trim_silence,
    )
    AOR.register_read("format_config", f"formats/{args.format}.json", __name__)

    # Load persisted AOR state
    aor_path = config.output_path() / ".artifact_registry.json"
    AOR.load(aor_path)

    # Standalone memory commands
    mw = MemoryWriter(_HERE)
    if args.memory_report:
        report = mw.store.report()
        print(f"Memory store: {report['total']} entries")
        for cat, count in report["counts"].items():
            print(f"  {cat}: {count}")
        print(f"  path: {report['path']}")
        return
    if args.memory_compact:
        removed = mw.store.compact()
        print(f"Memory compact: {removed} entries removed")
        return
    if args.fetch_analytics:
        from core.performance import PerformanceStore
        from core.upload import PERF_STORE
        from analysis.youtube_stats import fetch_stats
        store = PerformanceStore(PERF_STORE)
        pending = store.pending_ids()
        print(f"Performance store: {store.summary()}")
        if not pending:
            print("No pending videos to fetch.")
            return
        print(f"Fetching YouTube stats for {len(pending)} video(s)...")
        stats = fetch_stats(pending)
        if not stats:
            print("No stats returned (missing credentials or API error).")
            return
        for vid, s in stats.items():
            store.attach_stats(vid, s)
        store.save()
        print(f"Updated. {store.summary()}")
        return
    if args.propose_weights:
        from core.performance import PerformanceStore
        from core.upload import PERF_STORE
        from core.learning_engine import propose_weights, save_proposal
        store = PerformanceStore(PERF_STORE)
        proposal = propose_weights(list(store.records.values()))
        path = save_proposal(proposal, _HERE / "weights")
        print(f"[SIMULATION] proposal {path.stem} -> {path}")
        print(f"  samples={proposal['n_samples']} low_confidence={proposal['low_confidence']}")
        print(f"  dimension_weights={proposal['dimension_weights']}")
        print(f"  feature_lift={proposal['feature_lift']}")
        print("  NOTE: not applied — simulation only.")
        return

    # Memory dry-run flag — passed to _run_memory_writer after pipeline
    _memory_dry_run = args.memory_dry_run

    # ── Memory influence engine ────────────────────────────────
    from core.memory_influence import MemoryInfluenceEngine
    influence = MemoryInfluenceEngine(_HERE / "memory_store.json", mode=args.mode)
    influence_patch = influence.compute_patch()

    # ── Control arbiter — resolves all influence inputs ────────
    from core.control_arbiter import ControlArbiter, ArbitrationInput
    arbiter = ControlArbiter(trace_enabled=args.trace_arbiter)

    # Get StepTracker heuristics from local trace (if resuming)
    tracker = StepTracker(config.output_path())
    step_hints = tracker.heuristic_adjustments()

    arbiter_input = ArbitrationInput(
        memory_threshold_adjustments=influence_patch.threshold_adjustments,
        memory_scoring_bias=influence_patch.scoring_bias,
        memory_routing=influence_patch.pipeline_routing,
        step_threshold_adjustments=step_hints,
    )

    unified_config = arbiter.resolve(arbiter_input)
    flat_config = unified_config.to_flat_dict()

    if flat_config:
        log.info("ControlArbiter resolved runtime config (mode=%s)", args.mode)
        for section, values in flat_config.items():
            log.info("  %s: %s", section, values)
    if args.trace_arbiter:
        arbiter.print_trace()

    # Apply resolved config
    tracker.apply_influence(flat_config)
    registry.use("step_tracker")

    if args.resume:
        # Phase 2
        tracker.gate()
        sid = tracker.begin("phase_2")
        try:
            intro_path = Path(args.intro) if args.intro else None
            final = run_phase2(args.resume, config, intro_audio=intro_path, translate=args.translate)
            run_upload(final, config)
            tracker.complete(sid, artifacts=[str(final)], notes="Phase 2 render + upload done")
        except PipelineError as exc:
            tracker.fail(sid, reason=str(exc))
            log.error("Phase 2 failed: %s", exc)
            AOR.print_report()
            registry.print_report()
            AOR.save(aor_path)
            _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
            sys.exit(1)
        AOR.print_report()
        registry.print_report()
        AOR.save(aor_path)
        _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
        return

    if args.url:
        # Phase 1
        tracker.gate()
        sid = tracker.begin("phase_1")
        try:
            bias = flat_config.get("scoring_bias") if flat_config else None
            results = run_phase1(args.url, config, memory_bias=bias)
            artifacts = [str(r[1]) for r in results]
            tracker.complete(sid, artifacts=artifacts, notes=f"{len(results)} clips produced")
        except PipelineError as exc:
            tracker.fail(sid, reason=str(exc))
            log.error("Phase 1 failed: %s", exc)
            AOR.print_report()
            registry.print_report()
            AOR.save(aor_path)
            _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
            sys.exit(1)

        AOR.print_report()
        registry.print_report()
        AOR.save(aor_path)
        _run_memory_writer(tracker, aor_path, _HERE, dry_run=_memory_dry_run)
        log.info("Pipeline complete. %d clips produced.", len(results))
        for clip_slug, clip_dir, _, hook, _ in results:
            rel = clip_dir.relative_to(config.output_path())
            log.info("  %s: hook='%s'", rel, hook)
        if config.upload_enabled:
            log.warning("Upload flag set but Phase 2 (captions+compose) not run yet.")
            log.warning("Run: python main.py --resume <path> --upload")
        return

    # No args
    print("Usage: python main.py <URL>")
    print("       python main.py --resume <clip_path>")
    print("       python main.py <URL> --upload")
    AOR.print_report()
    registry.print_report()
    sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except PipelineError as exc:
        log.error("=== PIPELINE FAILED at stage: %s ===", exc)
        AOR.print_report()
        registry.print_report()
        sys.exit(1)
    except KeyboardInterrupt:
        AOR.print_report()
        registry.print_report()
        log.warning("Pipeline interrupted by user")
        sys.exit(130)
    except Exception as exc:
        log.error("=== UNEXPECTED PIPELINE FAILURE: %s ===", exc, exc_info=True)
        AOR.print_report()
        registry.print_report()
        sys.exit(1)
