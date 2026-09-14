#!/usr/bin/env python3
"""
Run All CARLA Scenarios
Automatically runs all generated scenario scripts one by one,
verifies frame generation, and provides a detailed report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from carla_wine_bridge import WineRuntimeError, resolve_runtime_mode, run_python_script

RUNTIME_CHOICES = ["auto", "wine-bridge", "local"]


class ScenarioRunner:
    def __init__(self, duration: int = 60, runtime: str = "auto") -> None:
        self.duration = duration
        self.base_dir = Path(__file__).parent
        self.code_dir = self.base_dir / "generated_code"
        self.scenes_dir = self.base_dir / "scenes"
        self.runtime = resolve_runtime_mode(runtime)
        self.runtime_requested = runtime
        self.results = []

        print("Scenario Runner Initialized")
        print(f"Code directory: {self.code_dir}")
        print(f"Scenes directory: {self.scenes_dir}")
        print(f"Duration per scenario: {self.duration} seconds")
        print(f"Runtime mode: {self.runtime} (requested={self.runtime_requested})")

    def find_scenario_scripts(self):
        """Find all Python scripts in generated_code directory"""
        if not self.code_dir.exists():
            print(f"ERROR: Code directory not found: {self.code_dir}")
            return []

        scripts = sorted(self.code_dir.glob("*.py"))
        print(f"\nFound {len(scripts)} scenario scripts:")
        for idx, script in enumerate(scripts, 1):
            print(f"  {idx}. {script.name}")

        return scripts

    def get_scenario_name(self, script_path):
        """Extract scenario name from script filename"""
        return script_path.stem

    def run_scenario(self, script_path):
        """Run a single scenario script"""
        scenario_name = self.get_scenario_name(script_path)
        output_dir = self.scenes_dir / scenario_name

        print(f"\n{'='*60}")
        print(f"Running: {scenario_name}")
        print(f"{'='*60}")
        print(f"Script: {script_path}")
        print(f"Output: {output_dir}")
        print(f"Duration: {self.duration} seconds")
        print(f"Runtime: {self.runtime}")

        start_time = time.time()

        try:
            script_args = ["--duration", str(self.duration), "--output", str(output_dir)]
            print(f"\nExecuting args: {' '.join(script_args)}")
            print(f"Started at: {datetime.now().strftime('%H:%M:%S')}")

            result = run_python_script(
                script_path=script_path,
                script_args=script_args,
                runtime_mode=self.runtime,
                timeout=self.duration + 120,
                capture_output=True,
                text=True,
                cwd=self.base_dir,
            )

            elapsed_time = time.time() - start_time

            if result.returncode == 0:
                print(f"[PASS] Script completed successfully in {elapsed_time:.1f}s")
            else:
                print(f"[FAIL] Script failed with exit code {result.returncode}")
                print(f"\nSTDOUT:\n{result.stdout}")
                print(f"\nSTDERR:\n{result.stderr}")

            return {
                "success": result.returncode == 0,
                "elapsed_time": elapsed_time,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }

        except subprocess.TimeoutExpired:
            elapsed_time = time.time() - start_time
            print(f"[FAIL] Script timed out after {elapsed_time:.1f}s")
            return {
                "success": False,
                "elapsed_time": elapsed_time,
                "error": "Timeout",
            }
        except WineRuntimeError as err:
            elapsed_time = time.time() - start_time
            print(f"[FAIL] Runtime error: {err}")
            return {
                "success": False,
                "elapsed_time": elapsed_time,
                "error": f"Runtime error: {err}",
            }
        except Exception as err:
            elapsed_time = time.time() - start_time
            print(f"[FAIL] Error running script: {err}")
            return {
                "success": False,
                "elapsed_time": elapsed_time,
                "error": str(err),
            }

    def verify_frames(self, script_path):
        """Verify that frames were saved correctly"""
        scenario_name = self.get_scenario_name(script_path)
        output_dir = self.scenes_dir / scenario_name

        print(f"\nVerifying frames for: {scenario_name}")

        if not output_dir.exists():
            print(f"[FAIL] Output directory not found: {output_dir}")
            return {
                "frames_found": 0,
                "frames_expected": 0,
                "success": False,
                "error": "Directory not found",
            }

        frames = list(output_dir.glob("*.png"))
        frame_count = len(frames)

        expected_frames = self.duration * 20

        print(f"Frames found: {frame_count}")
        print(f"Frames expected: ~{expected_frames} (at 20 FPS)")

        min_expected = int(expected_frames * 0.9)
        success = frame_count >= min_expected

        if success:
            print(f"[PASS] Frame count verified ({frame_count} >= {min_expected})")
        else:
            print(f"[FAIL] Insufficient frames ({frame_count} < {min_expected})")

        if frames:
            print(f"Sample frames: {[f.name for f in frames[:3]]}")

        return {
            "frames_found": frame_count,
            "frames_expected": expected_frames,
            "success": success,
            "output_dir": str(output_dir),
        }

    def process_scenario(self, script_path):
        """Process a single scenario: run and verify"""
        scenario_name = self.get_scenario_name(script_path)

        print(f"\n{'#'*60}")
        print(f"# SCENARIO: {scenario_name}")
        print(f"{'#'*60}")

        run_result = self.run_scenario(script_path)
        verify_result = self.verify_frames(script_path)

        overall_success = run_result["success"] and verify_result["success"]

        result = {
            "scenario": scenario_name,
            "script": str(script_path),
            "success": overall_success,
            "run_result": run_result,
            "verify_result": verify_result,
            "timestamp": datetime.now().isoformat(),
        }

        if overall_success:
            print(f"\n[PASS] {scenario_name} - PASSED")
        else:
            print(f"\n[FAIL] {scenario_name} - FAILED")

        return result

    def run_all(self):
        """Run all scenarios sequentially"""
        print(f"\n{'='*60}")
        print("RUNNING ALL CARLA SCENARIOS")
        print(f"{'='*60}\n")

        scripts = self.find_scenario_scripts()

        if not scripts:
            print("No scenario scripts found!")
            return

        for idx, script in enumerate(scripts, 1):
            print(f"\n\n{'='*60}")
            print(f"PROCESSING SCENARIO {idx}/{len(scripts)}")
            print(f"{'='*60}")

            result = self.process_scenario(script)
            self.results.append(result)

            if idx < len(scripts):
                print("\nWaiting 5 seconds before next scenario...")
                time.sleep(5)

        self.print_summary()
        self.save_report()

    def print_summary(self):
        """Print summary of all scenarios"""
        print(f"\n\n{'='*60}")
        print("SUMMARY REPORT")
        print(f"{'='*60}\n")

        total = len(self.results)
        passed = sum(1 for r in self.results if r["success"])
        failed = total - passed

        print(f"Total scenarios: {total}")
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Success rate: {(passed / total * 100):.1f}%\n" if total else "Success rate: 0.0%\n")

        print(f"{'Scenario':<35} {'Status':<10} {'Frames':<10} {'Time':<10}")
        print(f"{'-'*70}")

        for result in self.results:
            status = "[PASS]" if result["success"] else "[FAIL]"
            frames = result["verify_result"]["frames_found"]
            elapsed = result["run_result"].get("elapsed_time", 0)

            print(f"{result['scenario']:<35} {status:<10} {frames:<10} {elapsed:<10.1f}s")

        print(f"\n{'='*60}")

    def save_report(self):
        """Save detailed report to file"""
        report_file = self.base_dir / f"scenario_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        with open(report_file, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "duration": self.duration,
                    "total_scenarios": len(self.results),
                    "passed": sum(1 for r in self.results if r["success"]),
                    "failed": sum(1 for r in self.results if not r["success"]),
                    "results": self.results,
                },
                handle,
                indent=2,
            )

        print(f"\nDetailed report saved to: {report_file}")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Run all generated CARLA scenarios")
    parser.add_argument("--duration", type=int, help="Duration in seconds per scenario")
    parser.add_argument("--runtime", choices=RUNTIME_CHOICES)
    parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    return parser.parse_args()


def _prompt_duration(default: int = 60) -> int:
    """Prompt user for duration with validation."""
    while True:
        try:
            duration_input = input(
                f"How many seconds do you want to run each scenario? (default: {default}): "
            ).strip()

            if duration_input == "":
                duration = default
                print(f"Using default duration: {duration} seconds")
                return duration

            duration = int(duration_input)
            if duration <= 0:
                print("Error: Duration must be a positive number. Please try again.")
                continue

            if duration < 10:
                confirm = input(
                    f"Warning: {duration} seconds is very short. Continue? (yes/no): "
                ).strip().lower()
                if confirm not in ["yes", "y"]:
                    continue

            print(f"Duration set to: {duration} seconds")
            return duration

        except ValueError:
            print("Error: Please enter a valid number.")
        except KeyboardInterrupt:
            print("\n\nOperation cancelled by user.")
            sys.exit(0)


def _prompt_runtime(default: str = "auto") -> str:
    """Prompt user for runtime adapter."""
    print("\nRuntime adapter options:")
    print("  1. Auto (wine-bridge on macOS, local otherwise)")
    print("  2. Wine bridge")
    print("  3. Local")

    while True:
        choice = input("Select runtime adapter (1/2/3) [default: 1]: ").strip()
        if choice in {"", "1"}:
            return default
        if choice == "2":
            return "wine-bridge"
        if choice == "3":
            return "local"
        print("Invalid choice. Please enter 1, 2, or 3.")


def main():
    """Main entry point"""
    args = parse_args()

    print("\n" + "=" * 60)
    print("CARLA SCENARIO RUNNER")
    print("=" * 60)
    print("\nThis script will run all generated scenarios sequentially")
    print("and verify that frames are saved correctly.\n")

    duration = args.duration if args.duration is not None else _prompt_duration(default=60)
    runtime = args.runtime if args.runtime else _prompt_runtime(default="auto")
    resolved_runtime = resolve_runtime_mode(runtime)

    print(f"\nReady to run all scenarios with {duration}s duration each.")
    print(f"Runtime mode: {resolved_runtime} (requested={runtime})")

    if not args.yes:
        confirm = input("Do you want to continue? (yes/no): ").strip().lower()
        if confirm not in ["yes", "y"]:
            print("Operation cancelled.")
            sys.exit(0)

    runner = ScenarioRunner(duration=duration, runtime=runtime)
    runner.run_all()


if __name__ == "__main__":
    main()
