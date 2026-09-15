
import os
import json
import argparse
from dataclasses import dataclass
from typing import List, Tuple, Optional

import numpy as np
import cv2
import torch
from ultralytics import YOLO

from segment_anything import sam_model_registry, SamPredictor


IMG_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class Det:
    score: float
    xyxy: Tuple[float, float, float, float]
    source: str  # "yolo" or "sam_refined"


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def iter_images(folder: str) -> List[str]:
    files = []
    for fn in os.listdir(folder):
        ext = os.path.splitext(fn)[1].lower()
        if ext in IMG_EXT:
            files.append(os.path.join(folder, fn))
    files.sort()
    return files


def clamp_xyxy(x1, y1, x2, y2, H, W):
    x1 = float(np.clip(x1, 0, W - 1))
    x2 = float(np.clip(x2, 0, W - 1))
    y1 = float(np.clip(y1, 0, H - 1))
    y2 = float(np.clip(y2, 0, H - 1))
    if x2 < x1: x1, x2 = x2, x1
    if y2 < y1: y1, y2 = y2, y1
    return (x1, y1, x2, y2)


def iou_xyxy(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter + 1e-9
    return inter / union


def nms(dets: List[Det], iou_thr: float = 0.6) -> List[Det]:
    dets = sorted(dets, key=lambda d: d.score, reverse=True)
    keep: List[Det] = []
    for d in dets:
        if all(iou_xyxy(d.xyxy, k.xyxy) < iou_thr for k in keep):
            keep.append(d)
    return keep


def mask_to_xyxy(mask: np.ndarray) -> Optional[Tuple[float, float, float, float]]:
    ys, xs = np.where(mask)
    if len(xs) == 0 or len(ys) == 0:
        return None
    x1, x2 = xs.min(), xs.max()
    y1, y2 = ys.min(), ys.max()
    return float(x1), float(y1), float(x2), float(y2)


@torch.no_grad()
def refine_with_sam(predictor: SamPredictor, bgr: np.ndarray, xyxy, min_mask_area_frac=0.0003):
    """
    Refine a bbox with SAM. Returns refined xyxy or None if fails.
    """
    H, W = bgr.shape[:2]
    x1, y1, x2, y2 = clamp_xyxy(*xyxy, H, W)
    box = np.array([x1, y1, x2, y2], dtype=np.float32)

    masks, scores, _ = predictor.predict(box=box[None, :], multimask_output=True)

    img_area = H * W
    best = None
    best_s = -1.0
    for m, s in zip(masks, scores):
        area_frac = float(m.sum()) / float(img_area)
        if area_frac < min_mask_area_frac:
            continue
        if float(s) > best_s:
            best_s = float(s)
            best = m

    if best is None:
        return None

    tight = mask_to_xyxy(best)
    if tight is None:
        return None

    rx1, ry1, rx2, ry2 = clamp_xyxy(*tight, H, W)

    # sanity: reject insane expansion
    orig_area = max(1.0, (x2 - x1) * (y2 - y1))
    new_area = max(1.0, (rx2 - rx1) * (ry2 - ry1))
    if new_area > 2.5 * orig_area:
        return None

    return (rx1, ry1, rx2, ry2)


def draw_numbered_boxes(bgr: np.ndarray, dets: List[Det]) -> np.ndarray:
    out = bgr.copy()
    for idx, d in enumerate(dets, start=1):
        x1, y1, x2, y2 = map(int, d.xyxy)
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 0, 255), 2)  # red
        cv2.putText(out, f"{idx}", (x1, max(24, y1 - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 2)
    return out


def save_json(path: str, img_path: str, dets: List[Det]):
    payload = {
        "image": img_path,
        "objects": [
            {
                "id": i,
                "bbox_xyxy": [round(float(v), 2) for v in d.xyxy],
                "score": round(float(d.score), 6),
                "source": d.source
            }
            for i, d in enumerate(dets, start=1)
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root_dir", type=str, required=True, help="Folder with scenario subfolders OR a single folder of images")
    ap.add_argument("--out_dir", type=str, required=True)

    ap.add_argument("--yolo_weights", type=str, default="yolov8s.pt")
    ap.add_argument("--yolo_conf", type=float, default=0.25)

    ap.add_argument("--sam_type", type=str, default="vit_b", choices=["vit_b", "vit_l", "vit_h"])
    ap.add_argument("--sam_ckpt", type=str, required=True)

    ap.add_argument("--top_k", type=int, default=3)
    ap.add_argument("--nms_iou", type=float, default=0.6)

    ap.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    args = ap.parse_args()

    ensure_dir(args.out_dir)
    overlays_root = os.path.join(args.out_dir, "overlays")
    ann_root = os.path.join(args.out_dir, "annotations")
    ensure_dir(overlays_root)
    ensure_dir(ann_root)

    # YOLO model
    yolo = YOLO(args.yolo_weights)

    # SAM
    sam = sam_model_registry[args.sam_type](checkpoint=args.sam_ckpt)
    sam.to(device=args.device)
    predictor = SamPredictor(sam)

    # Walk two levels: scenario / condition / images
    # Structure: root_dir/<scenario>/<day_night__weather>/<images>
    # If root_dir contains images directly, treat as single scenario.
    scenarios = []
    top_entries = sorted(os.listdir(args.root_dir))
    has_images_top = any(
        os.path.splitext(f)[1].lower() in IMG_EXT
        for f in top_entries
        if os.path.isfile(os.path.join(args.root_dir, f))
    )

    if has_images_top:
        # Flat folder — single scenario
        scenarios = [("images", args.root_dir)]
    else:
        for scen in top_entries:
            scen_path = os.path.join(args.root_dir, scen)
            if not os.path.isdir(scen_path):
                continue
            sub_entries = sorted(os.listdir(scen_path))
            has_images_scen = any(
                os.path.splitext(f)[1].lower() in IMG_EXT
                for f in sub_entries
                if os.path.isfile(os.path.join(scen_path, f))
            )
            if has_images_scen:
                # One level: root/<scenario>/<images>
                scenarios.append((scen, scen_path))
            else:
                # Two levels: root/<scenario>/<condition>/<images>
                for cond in sub_entries:
                    cond_path = os.path.join(scen_path, cond)
                    if os.path.isdir(cond_path):
                        scenarios.append((os.path.join(scen, cond), cond_path))

    for scen_name, scen_dir in scenarios:
        imgs = iter_images(scen_dir)
        if not imgs:
            continue

        scen_overlay_dir = os.path.join(overlays_root, scen_name if scen_name != "." else "images")
        scen_ann_dir = os.path.join(ann_root, scen_name if scen_name != "." else "images")
        ensure_dir(scen_overlay_dir)
        ensure_dir(scen_ann_dir)

        print(f"[{scen_name}] n_images={len(imgs)}")

        for img_path in imgs:
            bgr = cv2.imread(img_path)
            if bgr is None:
                print("  - skip unreadable:", img_path)
                continue

            H, W = bgr.shape[:2]

            # Set SAM image once per frame
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            predictor.set_image(rgb)

            # YOLO proposals (ignore class label, use confidence)
            res = yolo.predict(bgr, conf=args.yolo_conf, verbose=False, device=args.device)[0]
            dets: List[Det] = []

            if res.boxes is not None and len(res.boxes) > 0:
                xyxy = res.boxes.xyxy.cpu().numpy()
                confs = res.boxes.conf.cpu().numpy()

                # sort YOLO proposals by confidence
                idxs = np.argsort(-confs)
                # try a bit more than top_k because SAM/NMS might drop some
                idxs = idxs[: max(args.top_k * 6, 30)]

                for i in idxs:
                    x1, y1, x2, y2 = map(float, xyxy[i])
                    s = float(confs[i])

                    # reject tiny boxes
                    bw = max(1.0, x2 - x1)
                    bh = max(1.0, y2 - y1)
                    if bw * bh < 48 * 48:
                        continue

                    refined = refine_with_sam(predictor, bgr, (x1, y1, x2, y2))
                    if refined is None:
                        continue

                    dets.append(Det(score=s, xyxy=refined, source="sam_refined"))

            # NMS + top_k
            dets = nms(dets, iou_thr=args.nms_iou)
            dets = dets[: args.top_k]

            # Save
            stem = os.path.splitext(os.path.basename(img_path))[0]
            out_img = os.path.join(scen_overlay_dir, f"{stem}.png")
            out_js = os.path.join(scen_ann_dir, f"{stem}.json")

            overlay = draw_numbered_boxes(bgr, dets)
            cv2.imwrite(out_img, overlay)
            save_json(out_js, img_path, dets)

    print("Done.")
    print("Overlays:", overlays_root)
    print("JSON:", ann_root)


if __name__ == "__main__":
    main()
