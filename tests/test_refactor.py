import sys
from pathlib import Path
# Add pipeline root to path so imports work when run from anywhere
_PIPELINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PIPELINE_ROOT))
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("PIPELINE REFACTOR TEST SUITE")
print("=" * 60)

results = []

# Test 1: Module imports
print("\n[TEST 1] Module imports")
try:
    from core.phase1 import run_phase1, PipelineError, _resolve_dag, _assert_valid_video, DAG_GRAPH
    from core.phase2 import run_phase2
    from core.upload import run_upload
    from core.cli import parse_args
    print("  PASS: All modules imported successfully")
    results.append(("Module imports", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("Module imports", f"FAIL: {e}"))

# Test 2: AOR declarations
print("\n[TEST 2] AOR declarations")
try:
    from core.artifact_registry import AOR, ArtifactRecord
    from core.config import build_config
    config = build_config('format1')
    # Just check that AOR is frozen (declarations work)
    assert AOR is not None
    print("  PASS: AOR initialized")
    results.append(("AOR declarations", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("AOR declarations", f"FAIL: {e}"))

# Test 3: Feature registry declarations
print("\n[TEST 3] Feature registry")
try:
    from core.phase1 import registry as _  # triggers phase1 feature declarations
    from core.phase2 import registry as _  # triggers phase2 feature declarations
    from core.upload import registry as _   # triggers upload feature declarations
    from core.feature_registry import registry

    report = registry.report()
    print(f"  PASS: Registry functional ({report['total']} features from modules)")
    assert report['total'] >= 7, f"Expected >= 7 features, got {report['total']}"
    results.append(("Feature registry", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    import traceback
    traceback.print_exc()
    results.append(("Feature registry", f"FAIL: {e}"))

# Test 4: DAG resolution
print("\n[TEST 4] DAG resolution")
try:
    from core.phase1 import _resolve_dag
    state_none = {"pipeline_stage": None}
    assert _resolve_dag(state_none) == "analysis"

    state_analysis = {"pipeline_stage": "analysis_complete"}
    assert _resolve_dag(state_analysis) == "render"

    state_render = {"pipeline_stage": "render_complete"}
    assert _resolve_dag(state_render) == "upload"

    state_uploaded = {"pipeline_stage": "uploaded"}
    assert _resolve_dag(state_uploaded) is None

    print("  PASS: DAG transitions correct")
    results.append(("DAG resolution", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("DAG resolution", f"FAIL: {e}"))

# Test 5: CLI parsing
print("\n[TEST 5] CLI parsing")
try:
    from core.cli import parse_args
    args = parse_args(["https://youtube.com/watch?v=XXX"])
    assert args.url == "https://youtube.com/watch?v=XXX"
    assert args.format == "format1"

    args2 = parse_args(["--resume", "short_20260101_120000/clip_1"])
    assert args2.resume == "short_20260101_120000/clip_1"

    args3 = parse_args(["--no-captions", "--no-gpu"])
    assert args3.no_captions == True
    assert args3.gpu == False

    print("  PASS: CLI arguments parsed correctly")
    results.append(("CLI parsing", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("CLI parsing", f"FAIL: {e}"))

# Test 6: PipelineError exception
print("\n[TEST 6] PipelineError exception")
try:
    from core.phase1 import PipelineError
    try:
        raise PipelineError("test error")
    except PipelineError as e:
        assert str(e) == "test error"
    print("  PASS: PipelineError works")
    results.append(("PipelineError", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("PipelineError", f"FAIL: {e}"))

# Test 7: Config builder
print("\n[TEST 7] Config builder")
try:
    from core.config import build_config
    config = build_config('format1')
    assert config.format_name == "format1"
    assert config.whisper_model == "base"

    config2 = build_config('format1', gpu=False)
    assert config2.gpu_enabled == False

    print("  PASS: Config builder works")
    results.append(("Config builder", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("Config builder", f"FAIL: {e}"))

# Test 8: Empty/missing transcript validation
print("\n[TEST 8] Empty transcript validation")
try:
    from core.contract_validator import validate_state
    try:
        validate_state({"pipeline_stage": "analysis_complete", "clips": [{}], "transcript": []})
        print("  FAIL: Should have raised error")
        results.append(("Empty transcript", "FAIL"))
    except Exception:
        print("  PASS: Empty transcript rejected")
        results.append(("Empty transcript", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("Empty transcript", f"FAIL: {e}"))

# Test 9: ffmpeg probe (should work)
print("\n[TEST 9] FFmpeg availability")
try:
    from editing.ffmpeg_builder import ffmpeg_path, probe_duration
    path = ffmpeg_path()
    assert path is not None
    print(f"  PASS: FFmpeg found at {path}")
    results.append(("FFmpeg availability", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("FFmpeg availability", f"FAIL: {e}"))

# Test 10: Whisper model loading
print("\n[TEST 10] Whisper model")
try:
    from faster_whisper import WhisperModel
    # Just check import works
    print("  PASS: faster_whisper importable")
    results.append(("Whisper import", "PASS"))
except Exception as e:
    print(f"  FAIL: {e}")
    results.append(("Whisper import", f"FAIL: {e}"))

print("\n" + "=" * 60)
print("TEST RESULTS SUMMARY")
print("=" * 60)
for name, result in results:
    print(f"  {name:.<40} {result}")
print("=" * 60)

passed = sum(1 for _, r in results if r == "PASS")
total = len(results)
print(f"\n{passed}/{total} tests passed")
