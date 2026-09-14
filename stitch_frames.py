#!/usr/bin/env python3
"""
Stitch front, front_left, and front_right camera frames into a cylindrical panorama.

This script assumes a fixed yaw/FOV camera layout and blends overlaps using
cosine weights. It walks the scenes/ tree by default and writes a stitched/
subfolder per run directory.
"""

import argparse
import math
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


CAMERA_ORDER = ["front_left", "front", "front_right"]


def log(level: str, message: str) -> None:
    print(f"[{level}] {message}")


def frame_pattern(prefix: str) -> re.Pattern:
    return re.compile(rf"^{re.escape(prefix)}_frame_(\d{{8}})\.png$")


def has_frames(dir_path: str, prefix: str) -> bool:
    pattern = frame_pattern(prefix)
    try:
        for name in os.listdir(dir_path):
            if pattern.match(name):
                return True
    except FileNotFoundError:
        return False
    return False


def is_run_dir(path: str) -> bool:
    for prefix in CAMERA_ORDER:
        subdir = os.path.join(path, prefix)
        if not os.path.isdir(subdir):
            return False
        if not has_frames(subdir, prefix):
            return False
    return True


def collect_frames(dir_path: str, prefix: str) -> Dict[int, str]:
    pattern = frame_pattern(prefix)
    frames: Dict[int, str] = {}
    try:
        for name in os.listdir(dir_path):
            match = pattern.match(name)
            if match:
                idx = int(match.group(1))
                frames[idx] = name
    except FileNotFoundError:
        return {}
    return frames


def find_run_dirs(root: str, recursive: bool) -> List[str]:
    run_dirs: List[str] = []
    if recursive:
        for dirpath, dirnames, _ in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "stitched"]
            has_shots = any(re.match(r"^shot_\d+$", d) for d in dirnames)
            if has_shots:
                continue
            if is_run_dir(dirpath):
                run_dirs.append(dirpath)
    else:
        try:
            for entry in os.scandir(root):
                if not entry.is_dir():
                    continue
                if entry.name == "stitched":
                    continue
                if is_run_dir(entry.path):
                    run_dirs.append(entry.path)
        except FileNotFoundError:
            return []
    return run_dirs


def build_panorama_maps(
    width: int,
    height: int,
    fov_deg: float,
    yaw_deg_map: Dict[str, float],
) -> Tuple[int, int, Dict[str, np.ndarray], Dict[str, np.ndarray], Dict[str, np.ndarray]]:
    hfov_rad = math.radians(fov_deg)
    yaw_rad_map = {cam: math.radians(yaw) for cam, yaw in yaw_deg_map.items()}

    min_angle = min(yaw_rad_map.values()) - (hfov_rad / 2.0)
    max_angle = max(yaw_rad_map.values()) + (hfov_rad / 2.0)
    px_per_rad = width / hfov_rad

    pano_width = int(round((max_angle - min_angle) * px_per_rad))
    pano_height = height
    if pano_width <= 0 or pano_height <= 0:
        raise ValueError("Computed invalid panorama size.")

    f = (width / 2.0) / math.tan(hfov_rad / 2.0)
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0

    x_coords = np.arange(pano_width, dtype=np.float32)
    y_coords = np.arange(pano_height, dtype=np.float32)[:, None]
    theta = min_angle + (x_coords / px_per_rad)

    map_xs: Dict[str, np.ndarray] = {}
    map_ys: Dict[str, np.ndarray] = {}
    weights: Dict[str, np.ndarray] = {}

    for cam, yaw_rad in yaw_rad_map.items():
        theta_cam = theta - yaw_rad
        valid = np.abs(theta_cam) <= (hfov_rad / 2.0)

        x_src = f * np.tan(theta_cam) + cx
        cos_theta = np.cos(theta_cam)
        y_src = (y_coords - cy) * cos_theta + cy

        map_x = np.tile(x_src[None, :], (pano_height, 1)).astype(np.float32)
        map_y = y_src.astype(np.float32)
        if np.any(~valid):
            map_x[:, ~valid] = -1
            map_y[:, ~valid] = -1

        weight = np.cos((theta_cam / (hfov_rad / 2.0)) * (np.pi / 2.0))
        weight[~valid] = 0
        weight_map = np.tile(weight[None, :].astype(np.float32), (pano_height, 1))

        map_xs[cam] = map_x
        map_ys[cam] = map_y
        weights[cam] = weight_map

    return pano_width, pano_height, map_xs, map_ys, weights


def cleanup_output(output_dir: str) -> None:
    if not os.path.isdir(output_dir):
        return
    for name in os.listdir(output_dir):
        if name == "stitched_preview.mp4" or (
            name.startswith("stitched_frame_") and name.endswith(".png")
        ):
            try:
                os.remove(os.path.join(output_dir, name))
            except OSError:
                pass


def find_overlap_columns(weight_a: np.ndarray, weight_b: np.ndarray) -> Optional[Tuple[int, int]]:
    overlap = (weight_a[0] > 0) & (weight_b[0] > 0)
    cols = np.where(overlap)[0]
    if cols.size == 0:
        return None
    return int(cols[0]), int(cols[-1])


def compute_vertical_seam(diff: np.ndarray) -> np.ndarray:
    height, width = diff.shape
    if height == 0 or width == 0:
        return np.zeros((height,), dtype=np.int32)

    dp = diff.copy()
    backtrack = np.zeros((height, width), dtype=np.int8)

    for y in range(1, height):
        prev = dp[y - 1]
        left = np.empty_like(prev)
        right = np.empty_like(prev)
        left[0] = np.inf
        left[1:] = prev[:-1]
        right[-1] = np.inf
        right[:-1] = prev[1:]
        choices = np.stack([left, prev, right], axis=0)
        idx = np.argmin(choices, axis=0)
        dp[y] = diff[y] + choices[idx, np.arange(width)]
        backtrack[y] = idx.astype(np.int8) - 1

    seam = np.zeros((height,), dtype=np.int32)
    seam[-1] = int(np.argmin(dp[-1]))
    for y in range(height - 1, 0, -1):
        seam[y - 1] = seam[y] + int(backtrack[y, seam[y]])
        seam[y - 1] = max(0, min(width - 1, seam[y - 1]))
    return seam


def compute_seam_mask(
    left_img: np.ndarray,
    right_img: np.ndarray,
    overlap_cols: Tuple[int, int],
    pano_width: int,
    edge_weight: float,
    bias_weight: float,
    bias_direction: str,
) -> np.ndarray:
    col_start, col_end = overlap_cols
    if col_end <= col_start:
        return np.ones((left_img.shape[0], pano_width), dtype=bool)

    left_gray = cv2.cvtColor(left_img, cv2.COLOR_BGR2GRAY)
    right_gray = cv2.cvtColor(right_img, cv2.COLOR_BGR2GRAY)
    diff = np.abs(left_gray.astype(np.float32) - right_gray.astype(np.float32))

    if edge_weight > 0:
        grad_left_x = cv2.Sobel(left_gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_left_y = cv2.Sobel(left_gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_right_x = cv2.Sobel(right_gray, cv2.CV_32F, 1, 0, ksize=3)
        grad_right_y = cv2.Sobel(right_gray, cv2.CV_32F, 0, 1, ksize=3)
        grad_left = cv2.magnitude(grad_left_x, grad_left_y)
        grad_right = cv2.magnitude(grad_right_x, grad_right_y)
        edge = grad_left + grad_right
        edge_norm = cv2.normalize(edge, None, 0, 255, cv2.NORM_MINMAX)
        diff = diff + edge_weight * edge_norm

    if bias_weight > 0:
        width = diff.shape[1]
        if width > 1:
            norm = np.linspace(0.0, 1.0, width, dtype=np.float32)
            if bias_direction == "left":
                bias = norm
            elif bias_direction == "right":
                bias = 1.0 - norm
            else:
                bias = np.zeros_like(norm)
            diff = diff + (bias_weight * 255.0) * bias[None, :]

    diff_slice = diff[:, col_start : col_end + 1]
    seam = compute_vertical_seam(diff_slice)

    height = left_img.shape[0]
    mask = np.zeros((height, pano_width), dtype=bool)
    for y in range(height):
        x = seam[y] + col_start
        mask[y, : x + 1] = True
    return mask


def overlap_energy(img: np.ndarray, col_start: int, col_end: int) -> float:
    if col_end < col_start:
        return 0.0
    roi = img[:, col_start : col_end + 1]
    if roi.size == 0:
        return 0.0
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(grad_x, grad_y)
    return float(np.mean(grad))


def choose_overlap_camera(
    left_img: np.ndarray,
    right_img: np.ndarray,
    overlap_cols: Tuple[int, int],
    preference: str,
    energy_ratio: float,
    default_choice: str,
) -> str:
    if preference in ("left", "right"):
        return preference
    if preference == "side":
        return "left" if default_choice == "right" else "right"
    if preference == "front":
        return default_choice
    if preference != "auto":
        return default_choice

    col_start, col_end = overlap_cols
    left_energy = overlap_energy(left_img, col_start, col_end)
    right_energy = overlap_energy(right_img, col_start, col_end)
    if left_energy <= 1e-6 and right_energy <= 1e-6:
        return default_choice
    if right_energy <= 1e-6:
        return "left"
    if left_energy <= 1e-6:
        return "right"

    ratio = left_energy / right_energy
    if ratio > energy_ratio:
        return "left"
    if ratio < 1.0 / energy_ratio:
        return "right"
    return default_choice


def process_run(
    run_dir: str,
    output_subdir: str,
    fov_deg: float,
    yaw_deg_map: Dict[str, float],
    video_fps: float,
    blend_mode: str,
    blend_power: float,
    seam_edge_weight: float,
    seam_bias_weight: float,
    seam_bias: str,
    overlap_preference: str,
    overlap_energy_ratio: float,
    overwrite: bool,
) -> None:
    front_dir = os.path.join(run_dir, "front")
    left_dir = os.path.join(run_dir, "front_left")
    right_dir = os.path.join(run_dir, "front_right")

    front_frames = collect_frames(front_dir, "front")
    left_frames = collect_frames(left_dir, "front_left")
    right_frames = collect_frames(right_dir, "front_right")

    all_ids = sorted(set(front_frames) | set(left_frames) | set(right_frames))
    common_ids: List[int] = []
    for frame_id in all_ids:
        missing = []
        if frame_id not in front_frames:
            missing.append("front")
        if frame_id not in left_frames:
            missing.append("front_left")
        if frame_id not in right_frames:
            missing.append("front_right")
        if missing:
            log("SKIP", f"{run_dir} frame {frame_id:08d} missing {', '.join(missing)}")
            continue
        common_ids.append(frame_id)

    if not common_ids:
        log("WARN", f"No aligned frames found in {run_dir}")
        return

    output_dir = os.path.join(run_dir, output_subdir)
    if os.path.isdir(output_dir) and not overwrite:
        log("SKIP", f"Output exists, skipping {run_dir} (use --overwrite to regenerate)")
        return

    os.makedirs(output_dir, exist_ok=True)
    if overwrite:
        cleanup_output(output_dir)

    first_id = common_ids[0]
    front_path = os.path.join(front_dir, front_frames[first_id])
    left_path = os.path.join(left_dir, left_frames[first_id])
    right_path = os.path.join(right_dir, right_frames[first_id])

    front_img = cv2.imread(front_path)
    left_img = cv2.imread(left_path)
    right_img = cv2.imread(right_path)

    if front_img is None or left_img is None or right_img is None:
        log("ERROR", f"Failed to read first frame images in {run_dir}")
        return

    height, width = front_img.shape[:2]
    if left_img.shape[:2] != (height, width) or right_img.shape[:2] != (height, width):
        log("ERROR", f"Camera image sizes do not match in {run_dir}")
        return

    try:
        pano_width, pano_height, map_xs, map_ys, weights = build_panorama_maps(
            width, height, fov_deg, yaw_deg_map
        )
    except ValueError as exc:
        log("ERROR", f"{run_dir}: {exc}")
        return

    video_path = os.path.join(output_dir, "stitched_preview.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(video_path, fourcc, video_fps, (pano_width, pano_height))
    if not writer.isOpened():
        log("WARN", f"Unable to open video writer for {video_path}. Video will be skipped.")
        writer = None

    overlap_left_front = find_overlap_columns(weights["front_left"], weights["front"])
    overlap_front_right = find_overlap_columns(weights["front"], weights["front_right"])

    for frame_id in common_ids:
        front_path = os.path.join(front_dir, front_frames[frame_id])
        left_path = os.path.join(left_dir, left_frames[frame_id])
        right_path = os.path.join(right_dir, right_frames[frame_id])

        front_img = cv2.imread(front_path)
        left_img = cv2.imread(left_path)
        right_img = cv2.imread(right_path)

        if front_img is None or left_img is None or right_img is None:
            log("SKIP", f"{run_dir} frame {frame_id:08d} unreadable image")
            continue

        warped_images: List[np.ndarray] = []
        weight_maps: List[np.ndarray] = []

        for cam, img in [
            ("front_left", left_img),
            ("front", front_img),
            ("front_right", right_img),
        ]:
            warped = cv2.remap(
                img,
                map_xs[cam],
                map_ys[cam],
                interpolation=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT,
                borderValue=0,
            )
            weight = weights[cam]
            if blend_mode == "soft" and blend_power != 1.0:
                weight = np.power(weight, blend_power)
            warped_images.append(warped)
            weight_maps.append(weight)

        if blend_mode == "soft":
            pano_accum = np.zeros((pano_height, pano_width, 3), dtype=np.float32)
            weight_sum = np.zeros((pano_height, pano_width), dtype=np.float32)
            for warped, weight in zip(warped_images, weight_maps):
                pano_accum += warped.astype(np.float32) * weight[:, :, None]
                weight_sum += weight
            pano = np.zeros_like(pano_accum)
            valid = weight_sum > 1e-6
            pano[valid] = pano_accum[valid] / weight_sum[valid, None]
            pano_uint8 = np.clip(pano, 0, 255).astype(np.uint8)
        elif blend_mode == "dominant":
            left_warp, front_warp, right_warp = warped_images
            valid_left = weight_maps[0] > 0
            valid_front = weight_maps[1] > 0
            valid_right = weight_maps[2] > 0

            if overlap_left_front is None or overlap_front_right is None:
                weight_stack = np.stack(weight_maps, axis=0)
                best_idx = np.argmax(weight_stack, axis=0)
                pano_uint8 = np.zeros((pano_height, pano_width, 3), dtype=np.uint8)
                for idx, warped in enumerate(warped_images):
                    mask = (best_idx == idx) & (weight_stack[idx] > 0)
                    if np.any(mask):
                        pano_uint8[mask] = warped[mask]
            else:
                lf_start, lf_end = overlap_left_front
                fr_start, fr_end = overlap_front_right

                left_choice = choose_overlap_camera(
                    left_warp,
                    front_warp,
                    overlap_left_front,
                    overlap_preference,
                    overlap_energy_ratio,
                    "right",
                )
                right_choice = choose_overlap_camera(
                    front_warp,
                    right_warp,
                    overlap_front_right,
                    overlap_preference,
                    overlap_energy_ratio,
                    "left",
                )

                pano_uint8 = np.zeros((pano_height, pano_width, 3), dtype=np.uint8)

                left_only = np.zeros((pano_height, pano_width), dtype=bool)
                left_only[:, : lf_start] = True
                front_only = np.zeros((pano_height, pano_width), dtype=bool)
                front_only[:, lf_end + 1 : fr_start] = True
                right_only = np.zeros((pano_height, pano_width), dtype=bool)
                right_only[:, fr_end + 1 :] = True

                overlap_left = np.zeros((pano_height, pano_width), dtype=bool)
                overlap_left[:, lf_start : lf_end + 1] = True
                overlap_right = np.zeros((pano_height, pano_width), dtype=bool)
                overlap_right[:, fr_start : fr_end + 1] = True

                use_left = valid_left & left_only
                use_front = valid_front & front_only
                use_right = valid_right & right_only

                if left_choice == "left":
                    use_left |= valid_left & overlap_left
                else:
                    use_front |= valid_front & overlap_left

                if right_choice == "right":
                    use_right |= valid_right & overlap_right
                else:
                    use_front |= valid_front & overlap_right

                if np.any(use_left):
                    pano_uint8[use_left] = left_warp[use_left]
                if np.any(use_front):
                    pano_uint8[use_front] = front_warp[use_front]
                if np.any(use_right):
                    pano_uint8[use_right] = right_warp[use_right]
        elif blend_mode == "seam":
            left_warp, front_warp, right_warp = warped_images
            valid_left = weight_maps[0] > 0
            valid_front = weight_maps[1] > 0
            valid_right = weight_maps[2] > 0

            if overlap_left_front is None or overlap_front_right is None:
                weight_stack = np.stack(weight_maps, axis=0)
                best_idx = np.argmax(weight_stack, axis=0)
                pano_uint8 = np.zeros((pano_height, pano_width, 3), dtype=np.uint8)
                for idx, warped in enumerate(warped_images):
                    mask = (best_idx == idx) & (weight_stack[idx] > 0)
                    if np.any(mask):
                        pano_uint8[mask] = warped[mask]
            else:
                mask_left = compute_seam_mask(
                    left_warp,
                    front_warp,
                    overlap_left_front,
                    pano_width,
                    seam_edge_weight,
                    seam_bias_weight,
                    "left" if seam_bias == "front" else "right" if seam_bias == "side" else "none",
                )
                mask_front = compute_seam_mask(
                    front_warp,
                    right_warp,
                    overlap_front_right,
                    pano_width,
                    seam_edge_weight,
                    seam_bias_weight,
                    "right" if seam_bias == "front" else "left" if seam_bias == "side" else "none",
                )

                pano_uint8 = np.zeros((pano_height, pano_width, 3), dtype=np.uint8)

                use_left = valid_left & (~valid_front | mask_left)
                if np.any(use_left):
                    pano_uint8[use_left] = left_warp[use_left]

                use_front = valid_front & (~use_left)
                if np.any(use_front):
                    pano_uint8[use_front] = front_warp[use_front]

                use_right = valid_right & (~valid_front | ~mask_front)
                if np.any(use_right):
                    pano_uint8[use_right] = right_warp[use_right]
        else:
            weight_stack = np.stack(weight_maps, axis=0)
            best_idx = np.argmax(weight_stack, axis=0)
            pano_uint8 = np.zeros((pano_height, pano_width, 3), dtype=np.uint8)
            for idx, warped in enumerate(warped_images):
                mask = (best_idx == idx) & (weight_stack[idx] > 0)
                if np.any(mask):
                    pano_uint8[mask] = warped[mask]

        output_path = os.path.join(output_dir, f"stitched_frame_{frame_id:08d}.png")
        cv2.imwrite(output_path, pano_uint8)
        if writer is not None:
            writer.write(pano_uint8)

    if writer is not None:
        writer.release()

    log("INFO", f"Stitched output saved to {output_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stitch front/front_left/front_right camera frames into a panorama."
    )
    parser.add_argument("--root", default="scenes", help="Root directory to scan.")
    parser.add_argument(
        "--recursive",
        dest="recursive",
        action="store_true",
        default=True,
        help="Recursively scan for run directories (default).",
    )
    parser.add_argument(
        "--no-recursive",
        dest="recursive",
        action="store_false",
        help="Only scan the root directory.",
    )
    parser.add_argument(
        "--output-subdir",
        default="stitched",
        help="Output subfolder within each run directory.",
    )
    parser.add_argument("--fov-deg", type=float, default=110.0, help="Camera FOV.")
    parser.add_argument(
        "--yaw-deg",
        nargs=3,
        type=float,
        default=[-60.0, 0.0, 60.0],
        metavar=("LEFT", "FRONT", "RIGHT"),
        help="Yaw degrees for front_left, front, front_right cameras.",
    )
    parser.add_argument("--video-fps", type=float, default=20.0, help="MP4 preview FPS.")
    parser.add_argument(
        "--blend-mode",
        choices=["max", "soft", "seam", "dominant"],
        default="dominant",
        help="Blending mode: 'dominant' keeps overlap from splitting objects.",
    )
    parser.add_argument(
        "--seam-edge-weight",
        type=float,
        default=3.0,
        help="Edge penalty for seam finding (higher avoids cutting strong edges).",
    )
    parser.add_argument(
        "--seam-bias",
        choices=["front", "side", "none"],
        default="front",
        help="Bias seam placement toward front or side cameras.",
    )
    parser.add_argument(
        "--seam-bias-weight",
        type=float,
        default=1.5,
        help="Strength of seam bias (0 disables bias).",
    )
    parser.add_argument(
        "--overlap-preference",
        choices=["front", "side", "auto"],
        default="front",
        help="Which camera to prefer for overlap regions in dominant mode.",
    )
    parser.add_argument(
        "--overlap-energy-ratio",
        type=float,
        default=1.15,
        help="Energy ratio threshold for auto overlap selection.",
    )
    parser.add_argument(
        "--blend-power",
        type=float,
        default=2.0,
        help="Power for soft blending weights (higher = sharper).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing stitched outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root

    if not os.path.isdir(root):
        log("ERROR", f"Root directory not found: {root}")
        return 1

    if len(args.yaw_deg) != 3:
        log("ERROR", "Expected exactly 3 yaw values for front_left, front, front_right.")
        return 1

    yaw_deg_map = {
        "front_left": args.yaw_deg[0],
        "front": args.yaw_deg[1],
        "front_right": args.yaw_deg[2],
    }

    run_dirs = find_run_dirs(root, args.recursive)
    if not run_dirs:
        log("WARN", f"No run directories found under {root}")
        return 0

    log("INFO", f"Found {len(run_dirs)} run directories.")

    for run_dir in run_dirs:
        process_run(
            run_dir,
            args.output_subdir,
            args.fov_deg,
            yaw_deg_map,
            args.video_fps,
            args.blend_mode,
            args.blend_power,
            args.seam_edge_weight,
            args.seam_bias_weight,
            args.seam_bias,
            args.overlap_preference,
            args.overlap_energy_ratio,
            args.overwrite,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
