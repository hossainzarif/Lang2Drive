#!/usr/bin/env python3
"""
Automated CARLA Scene Generator
Reads scenes from Excel, generates code using Claude API, runs simulations,
and retains intervention-aware metrics across shots.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from anthropic import Anthropic
except ImportError:  # pragma: no cover - covered by runtime checks
    Anthropic = None

from dotenv import load_dotenv
from scene_excel_utils import read_unique_scenes_from_excel as read_scenes_excel_shared


# Load environment variables
load_dotenv()

# Setup logging to file
LOG_DIR = Path(__file__).parent
LOG_FILE = LOG_DIR / f"scene_generator_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
logger.info("Log file created at: %s", LOG_FILE)

# Pipeline simulation duration defaults
# Keep this aligned with prompt requirements: 25s at 20 FPS => 500 frames/camera target.
DEFAULT_TEST_DURATION_SECONDS = 25
DEFAULT_FULL_DURATION_SECONDS = 25

# LLM token budgets for code generation and fix passes.
CODE_MAX_TOKENS = 8192
CODE_MAX_TOKENS_RETRY = 12000
FIX_MAX_TOKENS = 7680
FIX_MAX_TOKENS_RETRY = 11500


def test_network_connectivity() -> None:
    """Test basic network connectivity and SSL."""
    logger.info("Testing network connectivity...")

    try:
        logger.info("Test 1: Checking HTTPS to api.anthropic.com...")
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            "https://api.anthropic.com", headers={"User-Agent": "Python/3.10"}
        )
        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            logger.info("HTTPS connection successful, status: %s", response.status)
    except ssl.SSLError as err:
        logger.error("SSL Error: %s", err)
        logger.info("Attempting with unverified SSL context...")
        try:
            ctx = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                logger.info("Unverified SSL worked, status: %s", response.status)
                logger.warning("SSL verification disabled - this is less secure")
        except Exception as err2:  # pragma: no cover - network dependent
            logger.error("Still failed: %s", err2)
    except Exception as err:  # pragma: no cover - network dependent
        logger.error("Network test failed: %s: %s", type(err).__name__, err)

    logger.info("Test 2: Environment variables...")
    for var in ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"]:
        logger.info("  %s: %s", var, os.environ.get(var, "not set"))


def extract_code_from_response(text: str) -> str:
    """Extract Python source code from an LLM response."""
    code_block_pattern = re.compile(r"```(?:python)?\s*\n?(.*?)\n?```", re.DOTALL)
    match = code_block_pattern.search(text)
    if match:
        return match.group(1).strip()

    stripped = text.strip()
    if stripped.endswith("```"):
        stripped = stripped[:-3].strip()
    if stripped.startswith("```python"):
        stripped = stripped[len("```python") :].strip()
    elif stripped.startswith("```"):
        stripped = stripped[3:].strip()
    return stripped


def classify_intervention_bucket(intervention_count: int) -> str:
    """Map intervention count to reporting bucket."""
    if intervention_count <= 0:
        return "no_human_intervention"
    if intervention_count == 1:
        return "two_shot_or_one_intervention"
    return "multishot_or_multi_intervention"


def success_rate(success: int, tested: int) -> float:
    """Safe success-rate calculation."""
    if tested <= 0:
        return 0.0
    return round((success / tested) * 100.0, 2)


def determine_skip_outcome(existing_assets_before_run: bool) -> Dict[str, Any]:
    """Apply confirmed skip semantics."""
    if existing_assets_before_run:
        return {
            "tested": True,
            "excluded_from_tested": False,
            "final_success": True,
            "skip_counted_as_pass": True,
        }
    return {
        "tested": False,
        "excluded_from_tested": True,
        "final_success": False,
        "skip_counted_as_pass": False,
    }


def append_rows_dynamic_csv(csv_path: Path, new_rows: List[Dict[str, Any]]) -> None:
    """Append rows and automatically widen headers when new columns appear."""
    if not new_rows:
        return

    existing_rows: List[Dict[str, str]] = []
    existing_headers: List[str] = []

    if csv_path.exists():
        with open(csv_path, "r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_headers = list(reader.fieldnames or [])
            existing_rows = list(reader)

    headers = list(existing_headers)

    def add_header(col: str) -> None:
        if col not in headers:
            headers.append(col)

    for row in existing_rows:
        for key in row.keys():
            add_header(key)

    for row in new_rows:
        for key in row.keys():
            add_header(key)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()

        for row in existing_rows:
            normalized = {h: row.get(h, "") for h in headers}
            writer.writerow(normalized)

        for row in new_rows:
            normalized = {h: row.get(h, "") for h in headers}
            writer.writerow(normalized)


def write_single_row_csv(csv_path: Path, row: Dict[str, Any]) -> None:
    """Write a single-row CSV (overwriting previous contents)."""
    headers = list(row.keys())
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerow({h: row.get(h, "") for h in headers})


def flatten_record_for_csv(record: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten one scenario record into a wide CSV row with shot-specific columns."""
    row: Dict[str, Any] = {
        "run_id": record.get("run_id", ""),
        "timestamp": record.get("timestamp", ""),
        "execution_mode": record.get("execution_mode", ""),
        "scene_keyword": record.get("scene_keyword", ""),
        "scenario_keyword": record.get("scenario_keyword", ""),
        "tested": record.get("tested", False),
        "excluded_from_tested": record.get("excluded_from_tested", False),
        "was_skipped": record.get("was_skipped", False),
        "skip_counted_as_pass": record.get("skip_counted_as_pass", False),
        "existing_assets_before_run": record.get("existing_assets_before_run", False),
        "intervention_count": record.get("intervention_count", 0),
        "fix_rounds": record.get("fix_rounds", 0),
        "llm_generation_count": record.get("llm_generation_count", 0),
        "sim_runs": record.get("sim_runs", 0),
        "final_success": record.get("final_success", False),
        "final_bucket": record.get("final_bucket", ""),
        "final_status": record.get("final_status", ""),
        "error_notes": " | ".join(record.get("error_notes", [])),
    }

    for shot in record.get("shot_artifacts", []):
        idx = shot.get("shot_index", 0)
        prefix = f"shot_{idx}_"
        row[f"{prefix}prompt_text"] = shot.get("prompt_text", "")
        row[f"{prefix}user_adjustment_prompt"] = shot.get("user_adjustment_prompt", "")
        row[f"{prefix}prompt_file"] = shot.get("prompt_file", "")
        row[f"{prefix}full_prompt_file"] = shot.get("full_prompt_file", "")
        row[f"{prefix}code_file"] = shot.get("code_file", "")
        row[f"{prefix}scene_output_dir"] = shot.get("scene_output_dir", "")
        row[f"{prefix}sim_success"] = shot.get("sim_success", "")
        row[f"{prefix}frames_ok"] = shot.get("frames_ok", "")
        row[f"{prefix}accepted_by_user"] = shot.get("accepted_by_user", "")
        row[f"{prefix}status"] = shot.get("status", "")
        row[f"{prefix}timestamp"] = shot.get("timestamp", "")

    return row


def build_bucket_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute tested/success/fail/success-rate by intervention bucket."""
    buckets = {
        "no_human_intervention": {"tested": 0, "success": 0, "fail": 0, "success_rate": 0.0},
        "two_shot_or_one_intervention": {"tested": 0, "success": 0, "fail": 0, "success_rate": 0.0},
        "multishot_or_multi_intervention": {"tested": 0, "success": 0, "fail": 0, "success_rate": 0.0},
    }

    total_tested = 0
    total_success = 0

    for record in records:
        if not record.get("tested", False):
            continue

        bucket = classify_intervention_bucket(int(record.get("intervention_count", 0)))
        entry = buckets[bucket]

        entry["tested"] += 1
        total_tested += 1

        if record.get("final_success", False):
            entry["success"] += 1
            total_success += 1
        else:
            entry["fail"] += 1

    for key in buckets:
        buckets[key]["success_rate"] = success_rate(
            buckets[key]["success"], buckets[key]["tested"]
        )

    totals = {
        "tested": total_tested,
        "success": total_success,
        "fail": total_tested - total_success,
        "success_rate": success_rate(total_success, total_tested),
    }

    return {"buckets": buckets, "totals": totals}


def format_previous_shot_context(previous_shot: Optional[Dict[str, Any]]) -> str:
    """User-facing previous-shot summary used before collecting new fixes."""
    if not previous_shot:
        return ""

    lines = [
        f"Previous shot: shot_{previous_shot.get('shot_index', '?')}",
        f"Prompt file: {previous_shot.get('prompt_file', 'N/A')}",
    ]

    prompt_text = (previous_shot.get("prompt_text") or "").strip()
    if prompt_text:
        excerpt = prompt_text[:400]
        lines.append(f"Prompt excerpt: {excerpt}")

    adjustment = (previous_shot.get("user_adjustment_prompt") or "").strip()
    if adjustment:
        lines.append(f"Prior adjustment prompt: {adjustment[:400]}")

    return "\n".join(lines)


class SceneGenerator:
    def __init__(
        self,
        test_mode: bool = True,
        generate_only: bool = False,
        scenario_limit: Optional[int] = None,
        execution_mode: str = "interactive",
        max_attempts: int = 10,
        run_network_test: bool = False,
    ) -> None:
        self.test_mode = test_mode
        self.generate_only = generate_only
        self.scenario_limit = scenario_limit
        self.execution_mode = execution_mode
        self.max_attempts = max_attempts

        self.base_dir = Path(__file__).parent
        self.excel_path = self.base_dir / "Keyword Prompt Verification.xlsx"
        self.prompt_template_path = self.base_dir / "prompt.txt"
        self.prompts_dir = self.base_dir / "generated_prompts"
        self.code_dir = self.base_dir / "generated_code"
        self.scenes_dir = self.base_dir / "scenes"

        self.prompts_dir.mkdir(exist_ok=True)
        self.code_dir.mkdir(exist_ok=True)
        self.scenes_dir.mkdir(exist_ok=True)

        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.timestamp = datetime.now().isoformat()

        self.intervention_report_file = self.base_dir / f"intervention_report_{self.run_id}.json"
        self.intervention_summary_csv = self.base_dir / "intervention_summary.csv"
        self.scenario_intervention_csv = self.base_dir / "scenario_intervention_data.csv"
        self.run_summary_csv = self.base_dir / f"intervention_summary_{self.run_id}.csv"
        self.run_scenario_csv = self.base_dir / f"scenario_intervention_data_{self.run_id}.csv"

        if run_network_test:
            test_network_connectivity()

        api_key = os.getenv("Claude_API_Key")
        if not api_key:
            logger.error("Claude_API_Key not found in .env file")
            raise ValueError("Claude_API_Key not found in .env file")

        self._api_key = api_key
        self.client = None
        if Anthropic is not None:
            try:
                self.client = Anthropic(api_key=api_key, max_retries=0)
                logger.info("Anthropic client initialized")
            except Exception as init_error:  # pragma: no cover - environment dependent
                logger.warning("Failed to init Anthropic client: %s", init_error)
                self.client = None
        else:
            logger.warning("anthropic package not installed; using requests fallback only")

        with open(self.prompt_template_path, "r", encoding="utf-8") as handle:
            self.prompt_template = handle.read()

        self.results: List[Dict[str, Any]] = []

        if generate_only:
            mode_str = "GENERATE-ONLY"
        else:
            pipeline_mode = "TEST" if test_mode else "FULL"
            mode_str = f"{pipeline_mode} ({execution_mode.upper()})"

        logger.info("Initialized SceneGenerator in %s mode", mode_str)
        logger.info("Base directory: %s", self.base_dir)
        logger.info("Excel file: %s", self.excel_path)

        print(f"\nInitialized SceneGenerator in {mode_str} mode")
        print(f"Run ID: {self.run_id}")
        print(f"Base directory: {self.base_dir}")
        print(f"Excel file: {self.excel_path}")

    def _call_claude_api_via_requests(
        self, messages: List[Dict[str, str]], max_tokens: int = 1024
    ):
        """Call Claude API using requests library (Wine-compatible fallback)."""
        try:
            import requests
        except ImportError as err:  # pragma: no cover - env dependent
            logger.error("requests library not installed")
            raise ImportError("requests library required for API calls") from err

        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
        }
        payload = {
            "model": "claude-sonnet-4-5-20250929",
            "max_tokens": max_tokens,
            "messages": messages,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=180)
        response.raise_for_status()
        data = response.json()

        class SimpleResponse:
            def __init__(self, body: Dict[str, Any]) -> None:
                self.content = [type("Content", (), {"text": body["content"][0]["text"]})()]

        return SimpleResponse(data)

    def _call_claude_api(
        self, messages: List[Dict[str, str]], max_tokens: int = 1024, max_retries: int = 3
    ):
        """Call Claude API with retries."""
        last_error: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                logger.info("API call attempt %s/%s", attempt + 1, max_retries)
                return self._call_claude_api_via_requests(messages, max_tokens)
            except Exception as err:
                last_error = err
                logger.error("API call failed (attempt %s): %s", attempt + 1, err)
                if attempt < max_retries - 1:
                    wait_seconds = (attempt + 1) * 5
                    logger.info("Waiting %s seconds before retry...", wait_seconds)
                    time.sleep(wait_seconds)

        if last_error:
            raise last_error
        raise RuntimeError("Claude API failed without a captured error")

    @staticmethod
    def _code_looks_complete(code: str) -> bool:
        """Heuristic check for complete, runnable CARLA script."""
        normalized = (code or "").strip()
        if not normalized:
            return False
        if "def main" not in normalized:
            return False
        if "__name__" not in normalized or "main()" not in normalized:
            return False
        return True

    def _generate_code_with_token_retry(
        self,
        messages: List[Dict[str, str]],
        base_max_tokens: int,
        retry_max_tokens: int,
        context_label: str,
    ) -> str:
        """Call Claude and retry with higher token budget if code looks truncated."""
        response = self._call_claude_api(messages=messages, max_tokens=base_max_tokens)
        code = extract_code_from_response(response.content[0].text.strip())
        if self._code_looks_complete(code):
            return code

        logger.warning(
            "%s: Generated code looks incomplete (missing main). Retrying with max_tokens=%s",
            context_label,
            retry_max_tokens,
        )
        response_retry = self._call_claude_api(
            messages=messages, max_tokens=retry_max_tokens, max_retries=1
        )
        code_retry = extract_code_from_response(response_retry.content[0].text.strip())
        return code_retry or code

    @staticmethod
    def build_full_prompt(
        template: str,
        scenario_keyword: str,
        scene_prompt: str,
        scene_specifications: str,
    ) -> str:
        full_prompt = template.replace("{SCENE_KEYWORD}", scenario_keyword).replace(
            "{SCENE_PROMPT}",
            scene_prompt,
        )
        if "{SCENE_SPECIFICATIONS}" in full_prompt:
            full_prompt = full_prompt.replace("{SCENE_SPECIFICATIONS}", scene_specifications)
        elif scene_specifications.strip():
            full_prompt = (
                f"{full_prompt}\n\nSCENE_SPECIFICATIONS:\n{scene_specifications.strip()}\n"
            )
        return full_prompt

    def read_scenes_from_excel(self) -> List[Dict[str, Any]]:
        """Read all unique scenes from all sheets."""
        print("\nStep 1: Reading scenes from Excel (all sheets)...")

        scenes = read_scenes_excel_shared(self.excel_path)
        sheet_counts: Dict[str, int] = {}
        for scene in scenes:
            sheet_name = str(scene.get("sheet", "Unknown"))
            sheet_counts[sheet_name] = sheet_counts.get(sheet_name, 0) + 1

        for sheet_name in sorted(sheet_counts.keys()):
            print(f"  Sheet '{sheet_name}': {sheet_counts[sheet_name]} unique scenarios")

        print(f"Found {len(scenes)} unique scenes across {len(sheet_counts)} sheets")

        if self.test_mode:
            scenes = scenes[:2]
            print("TEST MODE: Processing only first 2 scenes")
        elif self.scenario_limit is not None:
            scenes = scenes[: self.scenario_limit]
            print(f"Processing first {len(scenes)} scenes")
        else:
            print(f"Processing all {len(scenes)} scenes")

        return scenes

    @staticmethod
    def generate_scenario_keyword(keyword: str) -> str:
        """Convert keyword into a filename-friendly scenario key."""
        scenario_keyword = keyword.lower().replace(" ", "_")
        scenario_keyword = "".join(c for c in scenario_keyword if c.isalnum() or c == "_")
        return scenario_keyword

    def _shot_paths(self, scenario_keyword: str, shot_index: int) -> Dict[str, Path]:
        """Return shot-specific prompt/code/output paths for the current run."""
        prompt_dir = self.prompts_dir / scenario_keyword / self.run_id / f"shot_{shot_index}"
        code_dir = self.code_dir / scenario_keyword / self.run_id / f"shot_{shot_index}"
        output_dir = self.scenes_dir / scenario_keyword / self.run_id / f"shot_{shot_index}"

        prompt_dir.mkdir(parents=True, exist_ok=True)
        code_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        return {
            "prompt_dir": prompt_dir,
            "code_dir": code_dir,
            "output_dir": output_dir,
            "prompt_file": prompt_dir / "enhanced_prompt.txt",
            "full_prompt_file": prompt_dir / "full_prompt.txt",
            "code_file": code_dir / f"{scenario_keyword}.py",
        }

    @staticmethod
    def _latest_file(paths: List[Path]) -> Optional[Path]:
        existing = [p for p in paths if p.exists()]
        if not existing:
            return None
        return max(existing, key=lambda p: p.stat().st_mtime)

    def find_existing_assets(self, scenario_keyword: str) -> Dict[str, Any]:
        """Find pre-existing assets (legacy or shot-based) for skip semantics/reuse."""
        legacy_code = self.code_dir / f"{scenario_keyword}.py"
        legacy_prompt = self.prompts_dir / f"{scenario_keyword}.txt"

        shot_code_candidates = list(
            (self.code_dir / scenario_keyword).glob(f"**/shot_*/{scenario_keyword}.py")
        )
        shot_prompt_candidates = list(
            (self.prompts_dir / scenario_keyword).glob("**/shot_*/enhanced_prompt.txt")
        )

        latest_code = self._latest_file([legacy_code] + shot_code_candidates)
        latest_prompt = self._latest_file([legacy_prompt] + shot_prompt_candidates)

        scene_root = self.scenes_dir / scenario_keyword
        has_scene_dir = scene_root.exists()

        return {
            "legacy_code": legacy_code if legacy_code.exists() else None,
            "legacy_prompt": legacy_prompt if legacy_prompt.exists() else None,
            "latest_code": latest_code,
            "latest_prompt": latest_prompt,
            "has_assets": bool(latest_code or latest_prompt or has_scene_dir),
        }

    def _copy_existing_to_shot0(
        self, scene: Dict[str, Any], scenario_keyword: str, existing: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Copy latest existing assets into this run's shot_0 workspace."""
        shot_paths = self._shot_paths(scenario_keyword, 0)

        source_code = existing.get("latest_code")
        if not source_code:
            return None

        shutil.copy2(source_code, shot_paths["code_file"])

        prompt_text = scene["prompt"]
        source_prompt = existing.get("latest_prompt")
        if source_prompt:
            shutil.copy2(source_prompt, shot_paths["prompt_file"])
            try:
                prompt_text = source_prompt.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                prompt_text = scene["prompt"]
        else:
            shot_paths["prompt_file"].write_text(
                f"KEYWORD: {scene['keyword']}\nSCENARIO_KEYWORD: {scenario_keyword}\n\n"
                f"ENHANCED PROMPT:\n{scene['prompt']}\n",
                encoding="utf-8",
            )

        if source_prompt and source_prompt.name == "full_prompt.txt":
            shutil.copy2(source_prompt, shot_paths["full_prompt_file"])
        else:
            shot_paths["full_prompt_file"].write_text(
                "Reused existing code; full prompt unavailable in source artifacts.\n",
                encoding="utf-8",
            )

        return {
            "shot_index": 0,
            "prompt_text": prompt_text,
            "user_adjustment_prompt": "",
            "prompt_file": str(shot_paths["prompt_file"]),
            "full_prompt_file": str(shot_paths["full_prompt_file"]),
            "code_file": str(shot_paths["code_file"]),
            "scene_output_dir": str(shot_paths["output_dir"]),
            "sim_success": "",
            "frames_ok": "",
            "accepted_by_user": "",
            "status": "prepared_from_existing",
            "timestamp": datetime.now().isoformat(),
        }

    def generate_initial_shot(
        self, scene: Dict[str, Any], scenario_keyword: str
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], int]:
        """Generate shot_0 prompt and code from scenario input."""
        llm_calls = 0
        shot_paths = self._shot_paths(scenario_keyword, 0)

        print(f"\nStep 2: Generating enhanced prompt for '{scene['keyword']}'...")
        scene_specifications = str(scene.get("scene_specifications", "") or "")
        prompt_request = (
            "I need you to enhance this CARLA simulation prompt for better code generation.\n\n"
            f"Original Keyword: {scene['keyword']}\n"
            f"Original Prompt: {scene['prompt']}\n\n"
            f"Scene Specifications / Success Criteria: {scene_specifications}\n\n"
            "Please provide:\n"
            "1. An enhanced, more detailed prompt that includes specific technical details for CARLA implementation\n"
            "2. Keep the same intent but add details about actor placements, behaviors, and timing\n\n"
            "Return ONLY the enhanced prompt text, nothing else."
        )

        try:
            prompt_message = self._call_claude_api(
                messages=[{"role": "user", "content": prompt_request}],
                max_tokens=1024,
            )
            enhanced_prompt = prompt_message.content[0].text.strip()
            llm_calls += 1
        except Exception as err:
            logger.error("Prompt generation failed, fallback to original prompt: %s", err)
            enhanced_prompt = scene["prompt"]

        shot_paths["prompt_file"].write_text(
            f"KEYWORD: {scene['keyword']}\n"
            f"SCENARIO_KEYWORD: {scenario_keyword}\n"
            f"SHOT_INDEX: 0\n\n"
            f"ORIGINAL PROMPT:\n{scene['prompt']}\n\n"
            f"SCENE SPECIFICATIONS:\n{scene_specifications}\n\n"
            f"ENHANCED PROMPT:\n{enhanced_prompt}\n",
            encoding="utf-8",
        )

        final_prompt = self.build_full_prompt(
            template=self.prompt_template,
            scenario_keyword=scenario_keyword,
            scene_prompt=enhanced_prompt,
            scene_specifications=scene_specifications,
        )
        shot_paths["full_prompt_file"].write_text(final_prompt, encoding="utf-8")

        print(f"\nStep 3: Generating CARLA code for '{scenario_keyword}'...")
        try:
            code = self._generate_code_with_token_retry(
                messages=[{"role": "user", "content": final_prompt}],
                base_max_tokens=CODE_MAX_TOKENS,
                retry_max_tokens=CODE_MAX_TOKENS_RETRY,
                context_label=f"{scenario_keyword} shot_0",
            )
            llm_calls += 1
            shot_paths["code_file"].write_text(code, encoding="utf-8")
        except Exception as err:
            logger.error("Code generation failed for %s: %s", scenario_keyword, err)
            print(f"Error generating code with Claude: {err}")
            return None, enhanced_prompt, llm_calls

        shot_record = {
            "shot_index": 0,
            "prompt_text": enhanced_prompt,
            "user_adjustment_prompt": "",
            "prompt_file": str(shot_paths["prompt_file"]),
            "full_prompt_file": str(shot_paths["full_prompt_file"]),
            "code_file": str(shot_paths["code_file"]),
            "scene_output_dir": str(shot_paths["output_dir"]),
            "sim_success": "",
            "frames_ok": "",
            "accepted_by_user": "",
            "status": "generated",
            "timestamp": datetime.now().isoformat(),
        }

        print(f"Saved enhanced prompt to: {shot_paths['prompt_file']}")
        print(f"Saved generated code to: {shot_paths['code_file']}")
        return shot_record, enhanced_prompt, llm_calls

    def build_fix_prompt_context(
        self,
        scenario_keyword: str,
        enhanced_prompt: str,
        issues: str,
        current_code: str,
        shot_history: List[Dict[str, Any]],
    ) -> str:
        """Build fix prompt including strict must-fix and anti-regression guidance."""
        checklist = self._extract_must_fix_items(issues)
        checklist_block = "\n".join(f"- [ ] {item}" for item in checklist)
        guardrails = self._build_failure_guardrails(shot_history)
        guardrail_block = "\n".join(f"- {line}" for line in guardrails)

        history_lines: List[str] = []
        for shot in shot_history:
            shot_idx = shot.get("shot_index", "?")
            history_lines.append(f"SHOT {shot_idx}:")
            history_lines.append(f"- Prompt file: {shot.get('prompt_file', 'N/A')}")
            prompt_text = (shot.get("prompt_text") or "").strip()
            if prompt_text:
                history_lines.append(f"- Prompt excerpt: {self._truncate_text(prompt_text, 500)}")
            prior_adjustment = (shot.get("user_adjustment_prompt") or "").strip()
            if prior_adjustment:
                history_lines.append(
                    f"- User adjustment prompt: {self._truncate_text(prior_adjustment, 500)}"
                )
            history_lines.append(
                f"- Last run result: sim_success={shot.get('sim_success')}, frames_ok={shot.get('frames_ok')}, status={shot.get('status')}"
            )
            history_lines.append("")

        history_block = "\n".join(history_lines).strip() or "No prior shot history available."

        return f"""The following CARLA simulation code has issues. Please fix them.

SCENARIO: {scenario_keyword}
BASE SCENE PROMPT:
{enhanced_prompt}

PREVIOUS SHOTS (for context; avoid repeating past mistakes):
{history_block}

MUST-FIX CHECKLIST (all items required in next version):
{checklist_block}

DO-NOT-REPEAT FAILURES FROM PRIOR SHOTS:
{guardrail_block}

LATEST CODE TO FIX:
```python
{current_code}
```

LATEST ISSUES TO FIX:
{issues}

CRITICAL INSTRUCTION:
- Address every MUST-FIX checklist item in code logic.
- Do not repeat failures from the DO-NOT-REPEAT section.
- Preserve valid logic that already works.
- Return COMPLETE Python code only (no markdown)."""

    @staticmethod
    def _truncate_text(text: str, max_chars: int = 240) -> str:
        """Normalize and truncate text for prompts/logs."""
        normalized = " ".join((text or "").split())
        if len(normalized) <= max_chars:
            return normalized
        return normalized[: max_chars - 3] + "..."

    def _extract_must_fix_items(self, issues: str, max_items: int = 8) -> List[str]:
        """Extract concise fix checklist items from issue text."""
        items: List[str] = []
        for raw in (issues or "").splitlines():
            line = raw.strip()
            if not line:
                continue
            if line.upper() == line and line.endswith(":"):
                continue
            if line.startswith(("Traceback", "File \"", "STDOUT:", "STDERR:", "Partial STDOUT:")):
                continue
            cleaned = re.sub(r"^[\-\*\d\.\)\s]+", "", line).strip()
            if len(cleaned) < 6:
                continue
            cleaned = self._truncate_text(cleaned, 260)
            if cleaned not in items:
                items.append(cleaned)
            if len(items) >= max_items:
                break

        if items:
            return items

        fallback = self._truncate_text(issues or "Fix the latest simulation issues.", 260)
        return [fallback]

    def _build_failure_guardrails(
        self, shot_history: List[Dict[str, Any]], max_items: int = 8
    ) -> List[str]:
        """Create anti-regression guardrails from prior shots."""
        guardrails: List[str] = []
        for shot in reversed(shot_history):
            shot_idx = shot.get("shot_index", "?")
            status = shot.get("status", "unknown")
            sim_success = shot.get("sim_success", "")
            frames_ok = shot.get("frames_ok", "")
            user_adjustment = self._truncate_text(shot.get("user_adjustment_prompt", ""), 220)
            prompt_excerpt = self._truncate_text(shot.get("prompt_text", ""), 220)

            issue_source = ""
            if user_adjustment:
                issue_source = f"user feedback='{user_adjustment}'"
            elif prompt_excerpt:
                issue_source = f"prompt intent='{prompt_excerpt}'"

            summary = (
                f"shot_{shot_idx}: status={status}, sim_success={sim_success}, "
                f"frames_ok={frames_ok}"
            )
            if issue_source:
                summary = f"{summary}, {issue_source}"
            guardrails.append(summary)

            if len(guardrails) >= max_items:
                break

        if guardrails:
            return guardrails

        return ["No prior shot failures recorded; still preserve valid behavior from prior code."]

    def _build_shot_feedback_log_lines(self, shot_history: List[Dict[str, Any]]) -> List[str]:
        """Create compact previous-shot feedback lines for scene generator logs."""
        lines: List[str] = []
        for shot in shot_history:
            shot_idx = shot.get("shot_index", "?")
            status = shot.get("status", "unknown")
            sim_success = shot.get("sim_success", "")
            frames_ok = shot.get("frames_ok", "")
            adjustment = self._truncate_text(shot.get("user_adjustment_prompt", ""), 200)
            prompt_text = self._truncate_text(shot.get("prompt_text", ""), 200)

            parts = [f"shot_{shot_idx}", f"status={status}", f"sim_success={sim_success}", f"frames_ok={frames_ok}"]
            if adjustment:
                parts.append(f"user_adjustment={adjustment}")
            elif prompt_text:
                parts.append(f"prompt_excerpt={prompt_text}")
            lines.append(" | ".join(parts))
        return lines

    def generate_fix_shot(
        self,
        scenario_keyword: str,
        enhanced_prompt: str,
        current_code_file: Path,
        issues: str,
        next_shot_index: int,
        shot_history: List[Dict[str, Any]],
        user_adjustment_prompt: str,
    ) -> Optional[Dict[str, Any]]:
        """Generate a new shot_N code variant from issues and history."""
        logger.info("Generating fixed code for %s shot_%s", scenario_keyword, next_shot_index)
        logger.info(
            "Fix context latest issues: %s",
            self._truncate_text(issues.replace("\n", " "), 500),
        )
        if user_adjustment_prompt:
            logger.info(
                "Fix context user adjustment for shot_%s: %s",
                next_shot_index,
                self._truncate_text(user_adjustment_prompt, 300),
            )
        for line in self._build_shot_feedback_log_lines(shot_history):
            logger.info("Fix context previous shot: %s", line)

        try:
            current_code = current_code_file.read_text(encoding="utf-8")
        except Exception as err:
            logger.error("Failed reading current code for fixes: %s", err)
            return None

        shot_paths = self._shot_paths(scenario_keyword, next_shot_index)
        fix_prompt = self.build_fix_prompt_context(
            scenario_keyword=scenario_keyword,
            enhanced_prompt=enhanced_prompt,
            issues=issues,
            current_code=current_code,
            shot_history=shot_history,
        )

        shot_paths["full_prompt_file"].write_text(fix_prompt, encoding="utf-8")

        prompt_text_for_shot = user_adjustment_prompt or issues
        shot_paths["prompt_file"].write_text(
            f"SCENARIO_KEYWORD: {scenario_keyword}\n"
            f"SHOT_INDEX: {next_shot_index}\n"
            f"USER_ADJUSTMENT_PROMPT:\n{user_adjustment_prompt}\n\n"
            f"LATEST_ISSUES_TO_FIX:\n{issues}\n",
            encoding="utf-8",
        )

        try:
            fixed_code = self._generate_code_with_token_retry(
                messages=[{"role": "user", "content": fix_prompt}],
                base_max_tokens=FIX_MAX_TOKENS,
                retry_max_tokens=FIX_MAX_TOKENS_RETRY,
                context_label=f"{scenario_keyword} shot_{next_shot_index}",
            )
            shot_paths["code_file"].write_text(fixed_code, encoding="utf-8")
        except Exception as err:
            logger.error("Failed to generate fixed code for shot_%s: %s", next_shot_index, err)
            print(f"Error generating fixed code: {err}")
            return None

        print(f"Saved fixed code to: {shot_paths['code_file']}")
        return {
            "shot_index": next_shot_index,
            "prompt_text": prompt_text_for_shot,
            "user_adjustment_prompt": user_adjustment_prompt,
            "prompt_file": str(shot_paths["prompt_file"]),
            "full_prompt_file": str(shot_paths["full_prompt_file"]),
            "code_file": str(shot_paths["code_file"]),
            "scene_output_dir": str(shot_paths["output_dir"]),
            "sim_success": "",
            "frames_ok": "",
            "accepted_by_user": "",
            "status": "generated_fix",
            "timestamp": datetime.now().isoformat(),
        }

    def run_simulation(
        self, code_file: Path, output_dir: Path, duration_seconds: int
    ) -> Tuple[bool, Optional[str]]:
        """Run generated CARLA simulation code."""
        print(f"\nStep 4: Running simulation with code: {code_file}")
        timeout_seconds = duration_seconds + 120

        try:
            try:
                code_text = code_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                code_text = ""

            output_flag = "--output-dir" if "--output-dir" in code_text else "--output"
            cmd = [
                sys.executable,
                str(code_file),
                "--duration",
                str(duration_seconds),
                output_flag,
                str(output_dir),
            ]

            print(f"Command: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            print("\n--- Simulation Output ---")
            print(result.stdout)
            if result.stderr:
                print("\n--- Errors/Warnings ---")
                print(result.stderr)
            print("--- End Output ---\n")

            if result.returncode == 0:
                print("[SUCCESS] Simulation completed successfully")
                return True, None

            error_info = f"Exit code: {result.returncode}\n"
            if result.stdout:
                error_info += f"STDOUT:\n{result.stdout}\n"
            if result.stderr:
                error_info += f"STDERR:\n{result.stderr}\n"
            print(f"[FAILED] Simulation exited with code {result.returncode}")
            return False, error_info

        except subprocess.TimeoutExpired as err:
            print(f"[TIMEOUT] Simulation exceeded {timeout_seconds} seconds")
            error_info = f"Simulation timed out after {timeout_seconds} seconds\n"
            if err.stdout:
                error_info += f"Partial STDOUT:\n{err.stdout[-2000:]}\n"
            if err.stderr:
                error_info += f"STDERR:\n{err.stderr[-1000:]}\n"
            return False, error_info

        except Exception as err:
            logger.exception("Exception running simulation")
            return False, f"Exception: {type(err).__name__}: {err}"

    def verify_frames(
        self,
        scene_output_dir: Path,
        duration_seconds: int,
        min_success_ratio: float = 0.5,
    ) -> bool:
        """Verify frame output and accept >= min_success_ratio of expected frames."""
        print(f"\nStep 5: Verifying frames in: {scene_output_dir}")

        if not scene_output_dir.exists():
            print(f"ERROR: Scene directory not found: {scene_output_dir}")
            return False

        camera_views = ["front", "front_left", "front_right", "rear"]
        frame_counts: Dict[str, int] = {}

        for view in camera_views:
            view_dir = scene_output_dir / view
            if not view_dir.exists():
                continue

            frames = list(view_dir.glob(f"{view}_frame_*.png"))
            frame_counts[view] = len(frames)
            print(f"  {view.upper()} camera: {len(frames)} frames")

        expected_frames = duration_seconds * 20
        if not frame_counts:
            single_frames = list(scene_output_dir.glob("*.png"))
            captured = len(single_frames)
            ratio = captured / expected_frames if expected_frames > 0 else 0.0
            print(f"Found {captured} frame files in {scene_output_dir}")
            print(
                f"Frame coverage: {captured}/{expected_frames} "
                f"({ratio * 100:.1f}%), threshold={min_success_ratio * 100:.1f}%"
            )
            return ratio >= min_success_ratio

        if len(set(frame_counts.values())) > 1:
            print(f"WARNING: Frame counts differ across cameras: {frame_counts}")
        else:
            synced = next(iter(frame_counts.values()))
            print(f"All cameras synchronized: {synced} frames each")

        # Use best available camera stream for coverage threshold.
        best_stream_frames = max(frame_counts.values()) if frame_counts else 0
        ratio = best_stream_frames / expected_frames if expected_frames > 0 else 0.0
        print(
            f"Best-stream coverage: {best_stream_frames}/{expected_frames} "
            f"({ratio * 100:.1f}%), threshold={min_success_ratio * 100:.1f}%"
        )
        return ratio >= min_success_ratio

    def ask_use_existing_or_regenerate(
        self, scenario_keyword: str, existing: Dict[str, Any]
    ) -> str:
        """Interactive decision for existing assets."""
        print("\n" + "=" * 60)
        print(f"EXISTING FILES FOUND for '{scenario_keyword}'")
        print("=" * 60)

        if existing.get("latest_prompt"):
            print(f"  - Prompt: {existing['latest_prompt']}")
        if existing.get("latest_code"):
            print(f"  - Code: {existing['latest_code']}")

        print("\nOptions:")
        print("  1. Use existing code (copy to shot_0 for this run)")
        print("  2. Regenerate prompt and code")
        print("  3. Skip this scenario")

        while True:
            choice = input("\nYour choice (1/2/3): ").strip()
            if choice == "1":
                return "use_existing"
            if choice == "2":
                return "regenerate"
            if choice == "3":
                return "skip"
            print("Please enter 1, 2, or 3")

    @staticmethod
    def ask_rerun_simulation() -> str:
        """Interactive action after failed simulation."""
        print("\n" + "=" * 60)
        print("SIMULATION FAILED OR FRAME VERIFICATION FAILED")
        print("=" * 60)
        print("\nOptions:")
        print("  1. Rerun same shot")
        print("  2. Continue and generate next shot with fixes")
        print("  3. Skip this scenario")

        while True:
            choice = input("\nYour choice (1/2/3): ").strip()
            if choice == "1":
                return "rerun"
            if choice == "2":
                return "continue"
            if choice == "3":
                return "skip"
            print("Please enter 1, 2, or 3")

    def get_user_feedback(
        self,
        scenario_keyword: str,
        scene_output_dir: Path,
        previous_shot: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Collect user verification feedback in interactive mode."""
        print("\n" + "=" * 60)
        print(f"VERIFICATION for '{scenario_keyword}'")
        print("=" * 60)
        print(f"\nScene directory: {scene_output_dir}")
        print("\nPlease check:")
        print("  1. Camera views (front, front-left, front-right, rear)")
        print("  2. Image colors")
        print("  3. Scenario correctness")

        previous_context = format_previous_shot_context(previous_shot)
        if previous_context:
            print("\nPrevious shot context (for next fix prompt):")
            print(previous_context)

        while True:
            response = input("\nAre there any issues? (yes/no): ").strip().lower()
            if response in {"no", "n"}:
                return {"accepted": True, "issues": "", "skip": False}
            if response in {"yes", "y"}:
                issues = input("Describe the issues (used as next adjustment prompt): ").strip()
                retry = input("Generate next shot with fixes? (yes/no): ").strip().lower()
                if retry in {"yes", "y"}:
                    return {"accepted": False, "issues": issues, "skip": False}

                skip = input("Skip this scenario? (yes/no): ").strip().lower()
                if skip in {"yes", "y"}:
                    return {"accepted": False, "issues": issues, "skip": True}
                return {"accepted": False, "issues": issues, "skip": False}

            print("Please answer 'yes' or 'no'")

    @staticmethod
    def get_simulation_log_excerpt(scene_output_dir: Path, max_lines: int = 120) -> str:
        """Return tail excerpt from scenario simulation log if present."""
        if not scene_output_dir.exists():
            return ""

        candidates = sorted(
            scene_output_dir.glob("*_simulation.log"),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        if not candidates:
            return ""

        try:
            content = candidates[0].read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

        lines = content.splitlines()
        tail = lines[-max_lines:] if len(lines) > max_lines else lines
        return "\n".join(tail)

    def ask_continue_feedback_for_fix(self, runtime_error: Optional[str]) -> str:
        """Ask user for additional issue context before generating next fix shot."""
        print("\n" + "=" * 60)
        print("CONTINUE WITH NEXT FIX SHOT")
        print("=" * 60)
        print("Please provide what went wrong so Claude can apply targeted fixes.")
        if runtime_error:
            print("\nRuntime/compiler error summary (sent to Claude):")
            snippet = runtime_error[-1200:] if len(runtime_error) > 1200 else runtime_error
            print(snippet)

        while True:
            feedback = input(
                "\nDescribe the problem for next-shot fix prompt (required): "
            ).strip()
            if feedback:
                return feedback
            print("Please provide at least one issue detail.")

    @staticmethod
    def compile_auto_issues(
        runtime_error: Optional[str],
        frames_ok: bool,
        simulation_log_excerpt: str = "",
        user_feedback: str = "",
    ) -> str:
        """Generate fix instructions with runtime/log context and optional user feedback."""
        issues: List[str] = []
        if runtime_error:
            issues.append("RUNTIME/COMPILATION ISSUE DETECTED:")
            issues.append(runtime_error)
        if not frames_ok:
            issues.append("FRAME VERIFICATION FAILED: output frames missing or invalid.")
        if simulation_log_excerpt:
            issues.append("SIMULATION LOG EXCERPT (WARNINGS/ERRORS):")
            issues.append(simulation_log_excerpt)
        if user_feedback:
            issues.append("USER FEEDBACK FOR THIS CONTINUE-AND-FIX ATTEMPT:")
            issues.append(user_feedback)
        if not issues:
            issues.append("Simulation behavior did not meet expected outcome.")
        return "\n".join(issues)

    @staticmethod
    def clear_scene_frames(scene_output_dir: Path) -> None:
        """Remove previous frame images to avoid mixing runs in the same shot folder."""
        if not scene_output_dir.exists():
            return
        for path in scene_output_dir.rglob("*.png"):
            try:
                path.unlink()
            except Exception:
                continue

    def _mark_skip(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Apply skip semantics to record."""
        outcome = determine_skip_outcome(record["existing_assets_before_run"])
        record["was_skipped"] = True
        record["tested"] = outcome["tested"]
        record["excluded_from_tested"] = outcome["excluded_from_tested"]
        record["final_success"] = outcome["final_success"]
        record["skip_counted_as_pass"] = outcome["skip_counted_as_pass"]
        record["final_status"] = "SKIPPED_PASS" if outcome["skip_counted_as_pass"] else "SKIPPED_EXCLUDED"
        record["final_bucket"] = classify_intervention_bucket(record["intervention_count"])
        return record

    def process_scene(self, scene: Dict[str, Any]) -> Dict[str, Any]:
        """Process one scene end-to-end, including multi-shot intervention flow."""
        scenario_keyword = self.generate_scenario_keyword(scene["keyword"])
        print("\n" + "#" * 60)
        print(f"# Processing Scene: {scene['keyword']}")
        print("#" * 60)

        existing = self.find_existing_assets(scenario_keyword)

        record: Dict[str, Any] = {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "execution_mode": self.execution_mode if not self.generate_only else "generate_only",
            "scene_keyword": scene["keyword"],
            "scenario_keyword": scenario_keyword,
            "existing_assets_before_run": existing["has_assets"],
            "was_skipped": False,
            "skip_counted_as_pass": False,
            "tested": not self.generate_only,
            "excluded_from_tested": self.generate_only,
            "intervention_count": 0,
            "fix_rounds": 0,
            "llm_generation_count": 0,
            "sim_runs": 0,
            "final_success": False,
            "final_bucket": "",
            "final_status": "",
            "error_notes": [],
            "shot_artifacts": [],
        }

        current_shot: Optional[Dict[str, Any]] = None
        enhanced_prompt: Optional[str] = None

        if existing["latest_code"]:
            if not self.generate_only and self.execution_mode == "interactive":
                user_choice = self.ask_use_existing_or_regenerate(scenario_keyword, existing)
                if user_choice == "skip":
                    return self._mark_skip(record)
                if user_choice == "use_existing":
                    current_shot = self._copy_existing_to_shot0(scene, scenario_keyword, existing)
                    if current_shot:
                        try:
                            enhanced_prompt = Path(current_shot["prompt_file"]).read_text(
                                encoding="utf-8", errors="ignore"
                            )
                        except Exception:
                            enhanced_prompt = scene["prompt"]
                    else:
                        record["error_notes"].append("Failed copying existing assets to shot_0.")
                else:  # regenerate
                    current_shot, enhanced_prompt, llm_calls = self.generate_initial_shot(
                        scene, scenario_keyword
                    )
                    record["llm_generation_count"] += llm_calls
            else:
                current_shot = self._copy_existing_to_shot0(scene, scenario_keyword, existing)
                if current_shot:
                    try:
                        enhanced_prompt = Path(current_shot["prompt_file"]).read_text(
                            encoding="utf-8", errors="ignore"
                        )
                    except Exception:
                        enhanced_prompt = scene["prompt"]

        if current_shot is None:
            current_shot, enhanced_prompt, llm_calls = self.generate_initial_shot(scene, scenario_keyword)
            record["llm_generation_count"] += llm_calls

        if current_shot is None:
            record["final_success"] = False
            record["final_status"] = "FAILED_INITIAL_GENERATION"
            record["final_bucket"] = classify_intervention_bucket(record["intervention_count"])
            return record

        record["shot_artifacts"].append(current_shot)

        if self.generate_only:
            record["final_success"] = True
            record["final_status"] = "GENERATED_ONLY"
            record["tested"] = False
            record["excluded_from_tested"] = True
            record["final_bucket"] = classify_intervention_bucket(record["intervention_count"])
            return record

        assert enhanced_prompt is not None

        duration = (
            DEFAULT_TEST_DURATION_SECONDS
            if self.test_mode
            else DEFAULT_FULL_DURATION_SECONDS
        )
        attempts = 0

        while attempts < self.max_attempts:
            attempts += 1
            print(f"\n--- Attempt {attempts}/{self.max_attempts} ---")

            current_shot = record["shot_artifacts"][-1]
            current_code_file = Path(current_shot["code_file"])
            current_output_dir = Path(current_shot["scene_output_dir"])

            record["sim_runs"] += 1
            sim_success, runtime_error = self.run_simulation(
                code_file=current_code_file,
                output_dir=current_output_dir,
                duration_seconds=duration,
            )
            frames_ok = self.verify_frames(
                current_output_dir,
                duration_seconds=duration,
                min_success_ratio=0.5,
            )

            current_shot["sim_success"] = sim_success
            current_shot["frames_ok"] = frames_ok

            if frames_ok:
                if not sim_success:
                    print(
                        "[INFO] Runtime issue detected but frame coverage reached threshold; "
                        "treating this shot as successful for workflow progression."
                    )
                if self.execution_mode == "autonomous":
                    current_shot["accepted_by_user"] = "autonomous"
                    current_shot["status"] = "passed"
                    record["final_success"] = True
                    record["final_status"] = "SUCCESS"
                    break

                previous_shot = record["shot_artifacts"][-2] if len(record["shot_artifacts"]) > 1 else None
                feedback = self.get_user_feedback(
                    scenario_keyword=scenario_keyword,
                    scene_output_dir=current_output_dir,
                    previous_shot=previous_shot,
                )

                if feedback["accepted"]:
                    current_shot["accepted_by_user"] = True
                    current_shot["status"] = "passed"
                    record["final_success"] = True
                    record["final_status"] = "SUCCESS"
                    break

                if feedback["skip"]:
                    current_shot["accepted_by_user"] = False
                    current_shot["status"] = "skipped"
                    return self._mark_skip(record)

                issues = feedback["issues"] or "User requested another shot with fixes."
                current_shot["accepted_by_user"] = False
                current_shot["status"] = "needs_fix"

                record["intervention_count"] += 1
                record["fix_rounds"] += 1

                next_idx = current_shot["shot_index"] + 1
                new_shot = self.generate_fix_shot(
                    scenario_keyword=scenario_keyword,
                    enhanced_prompt=enhanced_prompt,
                    current_code_file=current_code_file,
                    issues=issues,
                    next_shot_index=next_idx,
                    shot_history=record["shot_artifacts"],
                    user_adjustment_prompt=issues,
                )
                if new_shot is None:
                    record["error_notes"].append("Failed to generate user-requested fix shot")
                    break

                record["llm_generation_count"] += 1
                record["shot_artifacts"].append(new_shot)
                continue

            # Failure path
            current_shot["status"] = "failed_runtime_or_frames"
            continue_user_feedback = ""

            if self.execution_mode == "interactive":
                rerun_choice = self.ask_rerun_simulation()
                if rerun_choice == "rerun":
                    continue
                if rerun_choice == "skip":
                    return self._mark_skip(record)
                continue_user_feedback = self.ask_continue_feedback_for_fix(runtime_error)

            log_excerpt = self.get_simulation_log_excerpt(current_output_dir)
            auto_issues = self.compile_auto_issues(
                runtime_error,
                frames_ok,
                simulation_log_excerpt=log_excerpt,
                user_feedback=continue_user_feedback,
            )
            record["fix_rounds"] += 1

            reuse_shot_index = True
            next_idx = current_shot["shot_index"] if reuse_shot_index else current_shot["shot_index"] + 1
            new_shot = self.generate_fix_shot(
                scenario_keyword=scenario_keyword,
                enhanced_prompt=enhanced_prompt,
                current_code_file=current_code_file,
                issues=auto_issues,
                next_shot_index=next_idx,
                shot_history=record["shot_artifacts"],
                user_adjustment_prompt=continue_user_feedback,
            )
            if new_shot is None:
                record["error_notes"].append("Failed to generate auto-fix shot")
                break

            record["llm_generation_count"] += 1
            if reuse_shot_index:
                print(
                    f"[INFO] Reusing shot_{next_idx} folder after code error; "
                    "clearing previous frames before rerun."
                )
                self.clear_scene_frames(Path(new_shot["scene_output_dir"]))
                record["shot_artifacts"][-1] = new_shot
            else:
                record["shot_artifacts"].append(new_shot)

        if not record["final_success"] and not record["was_skipped"]:
            record["final_status"] = "FAILED"

        record["final_bucket"] = classify_intervention_bucket(record["intervention_count"])
        return record

    def print_summary(self, summary: Dict[str, Any]) -> None:
        """Print scenario-level and bucket-level summary."""
        print("\n" + "=" * 60)
        print("SUMMARY")
        print("=" * 60)

        for result in self.results:
            if result.get("excluded_from_tested"):
                status = "EXCLUDED"
            else:
                status = "SUCCESS" if result.get("final_success") else "FAILED"
            print(
                f"{result['scene_keyword']} -> {status} "
                f"(interventions={result['intervention_count']}, bucket={result['final_bucket']})"
            )

        print("\nIntervention Buckets:")
        bucket_labels = {
            "no_human_intervention": "No human intervention",
            "two_shot_or_one_intervention": "2-shot / one intervention",
            "multishot_or_multi_intervention": "Multishot / >1 interventions",
        }
        for key, label in bucket_labels.items():
            data = summary["buckets"][key]
            print(
                f"- {label}: Tested={data['tested']} Success={data['success']} "
                f"Fail={data['fail']} Success Rate={data['success_rate']:.2f}%"
            )

        totals = summary["totals"]
        print(
            f"\nOverall Tested={totals['tested']} Success={totals['success']} "
            f"Fail={totals['fail']} Success Rate={totals['success_rate']:.2f}%"
        )

    def save_reports(self, summary: Dict[str, Any]) -> None:
        """Persist final per-run JSON report and run-summary CSV rows."""
        report_payload = {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "execution_mode": self.execution_mode if not self.generate_only else "generate_only",
            "generate_only": self.generate_only,
            "test_mode": self.test_mode,
            "scenario_limit": self.scenario_limit,
            "max_attempts": self.max_attempts,
            "completed": True,
            "last_updated": datetime.now().isoformat(),
            "bucket_summary": summary,
            "results": self.results,
        }

        with open(self.intervention_report_file, "w", encoding="utf-8") as handle:
            json.dump(report_payload, handle, indent=2)

        print(f"\nIntervention report saved to: {self.intervention_report_file}")

        # Run-level summary CSV
        run_summary_row = self._build_run_summary_row(summary)
        append_rows_dynamic_csv(self.intervention_summary_csv, [run_summary_row])
        write_single_row_csv(self.run_summary_csv, run_summary_row)
        print(f"Run summary CSV updated: {self.intervention_summary_csv}")
        print(f"Run summary CSV (per-run) updated: {self.run_summary_csv}")

    def _build_run_summary_row(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """Build a summary row for run-level CSVs."""
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "execution_mode": self.execution_mode if not self.generate_only else "generate_only",
            "generate_only": self.generate_only,
            "tested_total": summary["totals"]["tested"],
            "success_total": summary["totals"]["success"],
            "fail_total": summary["totals"]["fail"],
            "success_rate_total": summary["totals"]["success_rate"],
            "no_human_tested": summary["buckets"]["no_human_intervention"]["tested"],
            "no_human_success": summary["buckets"]["no_human_intervention"]["success"],
            "no_human_fail": summary["buckets"]["no_human_intervention"]["fail"],
            "no_human_success_rate": summary["buckets"]["no_human_intervention"]["success_rate"],
            "one_intervention_tested": summary["buckets"]["two_shot_or_one_intervention"]["tested"],
            "one_intervention_success": summary["buckets"]["two_shot_or_one_intervention"]["success"],
            "one_intervention_fail": summary["buckets"]["two_shot_or_one_intervention"]["fail"],
            "one_intervention_success_rate": summary["buckets"]["two_shot_or_one_intervention"]["success_rate"],
            "multi_intervention_tested": summary["buckets"]["multishot_or_multi_intervention"]["tested"],
            "multi_intervention_success": summary["buckets"]["multishot_or_multi_intervention"]["success"],
            "multi_intervention_fail": summary["buckets"]["multishot_or_multi_intervention"]["fail"],
            "multi_intervention_success_rate": summary["buckets"]["multishot_or_multi_intervention"]["success_rate"],
        }

    def save_progress(self, summary: Dict[str, Any], record: Optional[Dict[str, Any]] = None) -> None:
        """Persist partial reports after each scenario to avoid data loss."""
        report_payload = {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "execution_mode": self.execution_mode if not self.generate_only else "generate_only",
            "generate_only": self.generate_only,
            "test_mode": self.test_mode,
            "scenario_limit": self.scenario_limit,
            "max_attempts": self.max_attempts,
            "completed": False,
            "last_updated": datetime.now().isoformat(),
            "bucket_summary": summary,
            "results": self.results,
        }

        with open(self.intervention_report_file, "w", encoding="utf-8") as handle:
            json.dump(report_payload, handle, indent=2)

        run_summary_row = self._build_run_summary_row(summary)
        write_single_row_csv(self.run_summary_csv, run_summary_row)

        if record is not None:
            scenario_row = flatten_record_for_csv(record)
            append_rows_dynamic_csv(self.run_scenario_csv, [scenario_row])
            append_rows_dynamic_csv(self.scenario_intervention_csv, [scenario_row])

        print(f"[INFO] Progress saved: {self.intervention_report_file}")

    def run(self) -> None:
        """Main execution method."""
        print("\n" + "=" * 60)
        print("AUTOMATED CARLA SCENE GENERATOR")
        if self.generate_only:
            print("Mode: GENERATE-ONLY (no simulation)")
        else:
            pipeline_mode = (
                f"TEST (2 scenes, {DEFAULT_TEST_DURATION_SECONDS}s each)"
                if self.test_mode
                else f"FULL (all scenes, {DEFAULT_FULL_DURATION_SECONDS}s each)"
            )
            print(f"Mode: {pipeline_mode}, execution={self.execution_mode.upper()}")
        print("=" * 60)

        scenes = self.read_scenes_from_excel()
        if not scenes:
            print("No scenes found in Excel file!")
            return

        self.results = []
        for idx, scene in enumerate(scenes, 1):
            print(f"\n\nProcessing scene {idx}/{len(scenes)}")
            record = self.process_scene(scene)
            self.results.append(record)
            summary = build_bucket_summary(self.results)
            self.save_progress(summary, record=record)

        summary = build_bucket_summary(self.results)
        self.print_summary(summary)
        self.save_reports(summary)


def main() -> None:
    """Main entry point."""
    print("\n" + "=" * 60)
    print("AUTOMATED CARLA SCENE GENERATOR")
    print("=" * 60)
    print("\nThis script generates CARLA simulation code from Excel scenarios.\n")

    print("Available pipeline modes:")
    print("  1. Generate-only: generate prompts and code only")
    print(
        f"  2. Test mode: process first 2 scenes with "
        f"{DEFAULT_TEST_DURATION_SECONDS}s simulation each"
    )
    print(
        f"  3. Full mode: process all scenes with "
        f"{DEFAULT_FULL_DURATION_SECONDS}s simulation each"
    )

    while True:
        try:
            mode_input = input("\nSelect mode (1/2/3) [default: 1]: ").strip()
            if mode_input in {"", "1"}:
                generate_only = True
                test_mode = False
                break
            if mode_input == "2":
                generate_only = False
                test_mode = True
                break
            if mode_input == "3":
                generate_only = False
                test_mode = False
                break
            print("Invalid choice. Please enter 1, 2, or 3.")
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
            sys.exit(0)

    execution_mode = "interactive"
    if not generate_only:
        print("\nExecution style:")
        print("  1. Interactive (current behavior with human feedback)")
        print("  2. Autonomous (no human intervention, auto-fix retries)")

        while True:
            choice = input("Select execution style (1/2) [default: 1]: ").strip()
            if choice in {"", "1"}:
                execution_mode = "interactive"
                break
            if choice == "2":
                execution_mode = "autonomous"
                break
            print("Invalid choice. Please enter 1 or 2.")

    scenario_limit: Optional[int]
    if generate_only:
        while True:
            try:
                count_input = (
                    input("\nHow many scenarios to generate? (number or 'all') [default: 5]: ")
                    .strip()
                    .lower()
                )
                if count_input == "":
                    scenario_limit = 5
                    break
                if count_input == "all":
                    scenario_limit = None
                    break
                scenario_limit = int(count_input)
                if scenario_limit <= 0:
                    print("Error: Must be a positive number.")
                    continue
                break
            except ValueError:
                print("Error: Please enter a number or 'all'.")
            except KeyboardInterrupt:
                print("\n\nOperation cancelled by user.")
                sys.exit(0)
    else:
        scenario_limit = None

    print("\nReady to start processing.")
    print(f"- Pipeline mode: {'GENERATE-ONLY' if generate_only else ('TEST' if test_mode else 'FULL')}")
    if not generate_only:
        print(f"- Execution mode: {execution_mode.upper()}")
        print("- Max attempts per scenario: 10")

    confirm = input("Do you want to continue? (yes/no): ").strip().lower()
    if confirm not in {"yes", "y"}:
        print("Operation cancelled.")
        sys.exit(0)

    run_network_test = os.getenv("SCENE_GENERATOR_NETWORK_TEST", "0") == "1"

    generator = SceneGenerator(
        test_mode=test_mode,
        generate_only=generate_only,
        scenario_limit=scenario_limit,
        execution_mode=execution_mode,
        max_attempts=10,
        run_network_test=run_network_test,
    )
    generator.run()


if __name__ == "__main__":
    main()
