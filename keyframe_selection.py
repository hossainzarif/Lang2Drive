#!/usr/bin/env python3
"""
CLIP-based keyframe selection (quality-first, no resource limits).

What this script does (per scenario folder):
1) Loads ALL frames (no subsampling).
2) Scores each frame with CLIP image-text similarity using:
   - CLIP-friendly prompt rewriting ("Dashcam view: ...")
   - optional prompt ensembling (max over multiple prompts)
3) Optionally boosts "event" moments using a motion/novelty term:
   novelty = 1 - cosine_similarity(frame_i, frame_{i-1})
4) Selects top-K keyframes using MMR (diversity-aware selection in embedding space).
5) Copies keyframes to an output folder with scores.

Dependencies:
  pip install open_clip_torch pillow tqdm

Run:
  python keyframe_selection_polished.py

Edit the CONFIG section (root_dir/out_dir, and if frames are in rgb subfolder).
"""

import os
import re
import glob
import shutil
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

import torch
from PIL import Image
from tqdm import tqdm
import open_clip


# =========================
# CONFIG
# =========================
@dataclass
class KeyframeConfig:
    # Root directory containing scenario folders
    root_dir: str

    # Output directory to save selected keyframes
    out_dir: str

    # If your frames are inside scenario/rgb, set this to "rgb"
    frames_subdir: Optional[str] = "rgb"  # e.g., "rgb" or None

    # Supported image patterns (checked in order)
    image_patterns: Tuple[str, ...] = ("*.png", "*.jpg", "*.jpeg", "*.webp")

    # Number of keyframes to select per scenario
    top_k: int = 10

    # Diversity selection strength (MMR): higher -> more relevance, lower -> more diversity
    mmr_lambda: float = 0.72  # typical 0.6~0.8

    # Optional motion/novelty weighting: set to 0.0 to disable.
    # final_score = (1-novelty_weight)*clip_score + novelty_weight*novelty
    novelty_weight: float = 0.25

    # Model
    model_name: str = "ViT-L-14"
    pretrained: str = "openai"  # or try "laion2b_s32b_b82k" if you prefer

    # Runtime
    batch_size: int = 128
    num_workers_decode: int = 0  # kept simple; PIL decode is single-threaded by default
    device: str = "cuda" if torch.cuda.is_available() else "cpu"

    # Precision
    use_fp16_on_cuda: bool = True

    # Saving
    save_scores_tsv: bool = True
    copy_files: bool = True  # if False, only writes TSV (no copying)


# =========================
# PROMPT HELPERS (CLIP-friendly)
# =========================

def clip_friendly_prompt(folder_name: str, long_prompt: str) -> str:
    """
    Make prompts more CLIP-friendly: concrete nouns + simple relations + dashcam viewpoint.
    """
    base = "Dashcam view: "

    # Prefer folder name cues (most reliable)
    rules = [
        ("RoadworksWithExcavator", "roadworks ahead with an excavator near the ego lane and cones on the road"),
        ("ParkingHGV", "a large truck parked partly in the lane near the roadside"),
        ("PedestrianCallingDog", "a pedestrian calling a dog near the curb by the road"),
        ("UnpredictableTaxi", "a taxi swerving or changing lanes in front of the ego vehicle"),
        ("UnpredictablePedestrianOnPhone", "a distracted pedestrian using a phone near the roadway"),
        ("CarWithItem_BRIEFCASE", "a car driving with a briefcase on the roof"),
        ("CarWithItem_TRAVELCASE", "a car driving with a suitcase on the roof"),
        ("CarWithItem_GUITARCASE", "a car driving with a guitar case on the roof"),
        ("BoyFootball", "a boy running into the road chasing a ball"),
        ("FootballHighway", "a ball rolling into the lane on a highway"),
        ("CowWithPedestrianCrossing", "a cow and a pedestrian crossing the road"),
        ("CarInOppositeDirection", "a wrong-way car facing the ego vehicle in the same lane"),
        ("PedestrianAdvesarial_front", "a pedestrian stepping into the ego lane in front of the vehicle"),
        ("PedestrianAdvesarial_back", "a pedestrian in the ego lane close to the vehicle"),
        ("CarForwardParkingWithDoors", "a parked car with doors open into the lane"),
        ("CarReverseParkingWithDoors", "a car reversing with doors open"),
        ("BlinkingYellowIntersection", "an intersection with blinking yellow traffic lights"),
        ("FallenTree", "a fallen tree blocking the lane ahead"),
        ("DangerousExcavator", "an excavator arm swinging close to the driving lane"),
        ("StaticHighwayAdPole", "a roadside advertisement pole close to the road edge"),
        ("SuddenSignAheadAndRight", "a warning sign indicating a sharp right turn ahead"),
        ("CarForwardStoppingDropoff", "a car ahead stopped in the lane for passenger drop-off"),
        ("RoadworksWithWorkers_VAN", "road workers with a van and cones partially blocking the lane"),
        ("RoadworksWithWorkers_NOVAN", "road workers with cones partially blocking the lane"),
        ("ShoppingcartRollingDown", "a shopping cart rolling into the ego lane"),
        ("BusObscuringCar", "a bus blocking the view of a car entering the lane"),
        ("WorkerFallingBarrel", "a barrel rolling into the lane near road workers"),
        ("WorkerFallingWendingMachine", "a vending machine fallen into the roadway"),
        ("EmergencyPlaneLanding", "a small airplane landing on the roadway ahead"),
        ("LooseZooAnimals", "animals loose on the road ahead"),
        ("HaybaleOnHighway", "a hay bale blocking the highway lane"),
        ("SquirrelRunningAcrossTheRoad", "a squirrel crossing the road in front of the vehicle"),
        ("PoliceCarChase", "multiple police cars chasing a vehicle through traffic"),
        ("EMSOutgoing", "an ambulance or EMS vehicle entering the road"),
        ("StaticEMSObstacle", "a stationary emergency vehicle blocking part of the lane"),
        ("RunnerInAPark", "a runner crossing near the roadway"),
        ("BusStopNearPlayground", "children near a playground by a bus stop close to the road"),
        ("StaticCarCrash", "a crashed car blocking part of the lane"),
        ("UnpredictableBicycle", "a cyclist swerving into the lane"),
    ]

    for key, short in rules:
        if key in folder_name:
            return base + short + "."

    # Fallback: keep it short and concrete by stripping abstract phrasing
    s = long_prompt
    s = re.sub(r"\b(imminent|risk|caution|required|forcing|harm|dangerous)\b", "", s, flags=re.IGNORECASE)
    s = s.replace("The ego vehicle approaches", "").replace("The vehicle reaches", "")
    s = s.strip(" .")
    if not s:
        s = "a driving scene with an unusual obstacle or hazard ahead"
    return base + s + "."

def prompt_ensemble(folder_name: str, long_prompt: str) -> List[str]:
    """
    Small ensemble: 3 variants per scenario.
    We take max similarity across prompts per frame (helps robustness).
    """
    p1 = clip_friendly_prompt(folder_name, long_prompt)

    # additional short variants
    # (keep short nouns + relations; no abstract language)
    p2 = p1.replace("Dashcam view: ", "")
    p2 = p2[0].upper() + p2[1:] if p2 else p1

    p3 = "Dashcam view: hazard ahead in the ego lane."

    # Some scenario-specific tweaks
    if "OppositeDirection" in folder_name:
        p3 = "Dashcam view: wrong-way car driving toward the ego vehicle."
    elif "FallenTree" in folder_name:
        p3 = "Dashcam view: tree trunk across the road blocking the lane."
    elif "Shoppingcart" in folder_name:
        p3 = "Dashcam view: shopping cart in the road ahead."
    elif "PoliceCarChase" in folder_name:
        p3 = "Dashcam view: police cars moving fast through traffic."
    elif "Roadworks" in folder_name:
        p3 = "Dashcam view: construction cones and workers on the road."

    return [p1, p2, p3]


# =========================
# FILE / FRAME HELPERS
# =========================

def numeric_sort_key(path: str) -> Tuple[int, str]:
    """
    Sort by last integer in filename if present; otherwise lexicographic.
    """
    base = os.path.basename(path)
    nums = re.findall(r"\d+", base)
    if nums:
        return (int(nums[-1]), base)
    return (10**18, base)

def list_frames(folder: str, patterns: Tuple[str, ...]) -> List[str]:
    frames: List[str] = []
    for pat in patterns:
        frames.extend(glob.glob(os.path.join(folder, pat)))
    frames = sorted(set(frames), key=numeric_sort_key)
    return frames


# =========================
# CLIP SELECTOR
# =========================

class CLIPKeyframeSelector:
    def __init__(self, cfg: KeyframeConfig):
        self.cfg = cfg
        self.device = torch.device(cfg.device)

        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            cfg.model_name, pretrained=cfg.pretrained
        )
        self.tokenizer = open_clip.get_tokenizer(cfg.model_name)

        self.model = self.model.to(self.device).eval()

        self.use_fp16 = bool(cfg.use_fp16_on_cuda and self.device.type == "cuda")
        if self.use_fp16:
            self.model = self.model.half()

        # Tiny speed tweaks
        if self.device.type == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True

    @torch.no_grad()
    def encode_texts(self, texts: List[str]) -> torch.Tensor:
        tokens = self.tokenizer(texts).to(self.device)
        tfeat = self.model.encode_text(tokens)
        tfeat = tfeat / tfeat.norm(dim=-1, keepdim=True)
        return tfeat  # [M, D]

    @torch.no_grad()
    def encode_images(self, image_paths: List[str]) -> torch.Tensor:
        feats = []
        bs = self.cfg.batch_size

        for i in range(0, len(image_paths), bs):
            batch_paths = image_paths[i:i+bs]
            imgs = []
            for p in batch_paths:
                img = Image.open(p).convert("RGB")
                imgs.append(self.preprocess(img))
            x = torch.stack(imgs, dim=0).to(self.device)
            if self.use_fp16:
                x = x.half()

            f = self.model.encode_image(x)
            f = f / f.norm(dim=-1, keepdim=True)
            feats.append(f)

        return torch.cat(feats, dim=0)  # [N, D]

    @staticmethod
    def cosine_matmul(a: torch.Tensor, b: torch.Tensor) -> torch.Tensor:
        """
        a: [N, D], b: [M, D] -> [N, M] = cosine similarity (assuming normalized).
        """
        return a @ b.T

    @staticmethod
    def novelty_scores(img_feats: torch.Tensor) -> torch.Tensor:
        """
        novelty[i] = 1 - cos(img[i], img[i-1]); novelty[0]=0
        img_feats assumed normalized. Returns [N] in [0,2].
        """
        if img_feats.size(0) <= 1:
            return torch.zeros((img_feats.size(0),), device=img_feats.device, dtype=img_feats.dtype)
        prev = img_feats[:-1]
        cur = img_feats[1:]
        sim_prev = (cur * prev).sum(dim=-1)  # [N-1]
        nov = 1.0 - sim_prev
        nov = torch.cat([torch.zeros((1,), device=img_feats.device, dtype=img_feats.dtype), nov], dim=0)
        return nov

    @staticmethod
    def select_mmr(
        paths: List[str],
        img_feats: torch.Tensor,      # [N, D], normalized
        scores: torch.Tensor,         # [N], higher is better
        top_k: int,
        lam: float
    ) -> List[int]:
        """
        MMR selection:
          pick frame maximizing: lam*relevance - (1-lam)*max_sim_to_selected
        """
        N = len(paths)
        top_k = min(top_k, N)
        if top_k <= 0:
            return []

        scores_cpu = scores.detach().float().cpu()
        # Start with the best by relevance
        first = int(torch.argmax(scores_cpu).item())
        selected = [first]

        # Precompute cosine sim matrix in chunks if needed (N can be large).
        # For simplicity (DGX, no constraints), we compute full NxN if feasible.
        # If N is enormous (e.g., >30k frames), switch to chunking.
        # Here: compute on-device to be fast.
        sim_mat = img_feats @ img_feats.T  # [N, N]

        candidates = torch.ones((N,), dtype=torch.bool, device=img_feats.device)
        candidates[first] = False

        for _ in range(top_k - 1):
            cand_idx = torch.where(candidates)[0]
            if cand_idx.numel() == 0:
                break

            # max similarity to any selected
            sel_idx = torch.tensor(selected, device=img_feats.device, dtype=torch.long)
            max_sim = sim_mat[cand_idx][:, sel_idx].max(dim=1).values  # [C]

            rel = scores[cand_idx]
            mmr = lam * rel - (1.0 - lam) * max_sim

            best_cand = cand_idx[torch.argmax(mmr).item()].item()
            selected.append(int(best_cand))
            candidates[best_cand] = False

        return selected

    def score_frames_for_scenario(
        self, folder_name: str, long_prompt: str, frame_paths: List[str]
    ) -> Tuple[torch.Tensor, torch.Tensor, List[str]]:
        """
        Returns:
          img_feats: [N, D]
          final_scores: [N]
          prompts_used: list[str]
        """
        # Encode images once
        img_feats = self.encode_images(frame_paths)  # [N, D], normalized

        # Prompt ensemble -> text feats [M, D]
        prompts = prompt_ensemble(folder_name, long_prompt)
        txt_feats = self.encode_texts(prompts)  # [M, D]

        # Similarities [N, M], take max across prompts
        sims = self.cosine_matmul(img_feats, txt_feats)  # [N, M]
        clip_score = sims.max(dim=1).values  # [N]

        # Optional novelty term (helps temporal events)
        if self.cfg.novelty_weight > 0.0:
            nov = self.novelty_scores(img_feats)  # [N]
            # normalize novelty roughly to 0..1 using clamp
            nov01 = nov.clamp(0.0, 1.0)
            w = float(self.cfg.novelty_weight)
            final = (1.0 - w) * clip_score + w * nov01
        else:
            final = clip_score

        return img_feats, final, prompts

    def select_keyframes(
        self,
        folder_name: str,
        long_prompt: str,
        frame_paths: List[str]
    ) -> List[Tuple[str, float]]:
        img_feats, final_scores, prompts_used = self.score_frames_for_scenario(
            folder_name, long_prompt, frame_paths
        )

        # MMR selection (diversity + relevance)
        selected_idx = self.select_mmr(
            frame_paths,
            img_feats=img_feats,
            scores=final_scores,
            top_k=self.cfg.top_k,
            lam=float(self.cfg.mmr_lambda),
        )

        selected = [(frame_paths[i], float(final_scores[i].detach().float().cpu().item())) for i in selected_idx]
        # Sort selected by score descending (for nicer output naming)
        selected.sort(key=lambda x: x[1], reverse=True)
        return selected

    def save_selected(self, scenario_name: str, selected: List[Tuple[str, float]]):
        os.makedirs(self.cfg.out_dir, exist_ok=True)
        out_scn_dir = os.path.join(self.cfg.out_dir, scenario_name)
        os.makedirs(out_scn_dir, exist_ok=True)

        rows = ["rank\tscore\toutput_filename\tsource_path"]
        for rank, (src, score) in enumerate(selected, start=1):
            ext = os.path.splitext(src)[1].lower()
            out_name = f"keyframe_{rank:02d}_score_{score:.5f}{ext}"
            dst = os.path.join(out_scn_dir, out_name)

            if self.cfg.copy_files:
                shutil.copy2(src, dst)

            rows.append(f"{rank}\t{score:.6f}\t{out_name}\t{src}")

        if self.cfg.save_scores_tsv:
            with open(os.path.join(out_scn_dir, "selected_keyframes.tsv"), "w") as f:
                f.write("\n".join(rows))


# =========================
# MAIN DRIVER
# =========================

def select_keyframes_from_scenarios(
    prompts_dict: Dict[str, str],
    cfg: KeyframeConfig,
    only_these: Optional[List[str]] = None
):
    selector = CLIPKeyframeSelector(cfg)

    scenario_names = list(prompts_dict.keys())
    if only_these is not None:
        allow = set(only_these)
        scenario_names = [s for s in scenario_names if s in allow]

    for scenario in tqdm(scenario_names, desc="Scenarios"):
        # Build frame directory path
        scenario_dir = os.path.join(cfg.root_dir, scenario)
        if cfg.frames_subdir is not None:
            frame_dir = os.path.join(scenario_dir, cfg.frames_subdir)
        else:
            frame_dir = scenario_dir

        if not os.path.isdir(frame_dir):
            print(f"[WARN] Missing frames folder: {frame_dir}")
            continue

        frame_paths = list_frames(frame_dir, cfg.image_patterns)
        if not frame_paths:
            print(f"[WARN] No frames found in: {frame_dir}")
            continue

        long_prompt = prompts_dict[scenario]
        selected = selector.select_keyframes(scenario, long_prompt, frame_paths)
        if not selected:
            print(f"[WARN] No selections for: {scenario}")
            continue

        selector.save_selected(scenario, selected)

    print(f"\nDone.\nSaved keyframes to: {cfg.out_dir}")


# =========================
# YOUR PROMPTS DICT HERE
# =========================

corner_case_prompts_dict = {
    "RoadworksWithExcavator": "The ego vehicle approaches a roadwork zone where a large excavator is operating close to the driving lane.",
    "ParkingHGV": "A heavy goods vehicle is attempting to park on a narrow roadside, partially blocking traffic.",
    "PedestrianCallingDog": "A pedestrian is standing near the curb, calling a dog that is moving unpredictably near the roadway.",
    "UnpredictableTaxi": "A taxi ahead is making sudden lane changes without clear signaling.",
    "UnpredictablePedestrianOnPhoneV2": "A pedestrian distracted by their phone suddenly steps toward the road without looking.",
    "CarWithItem_BRIEFCASE": "A car ahead has a briefcase placed loosely on its roof while driving.",
    "BoyFootball": "A young boy runs onto the street chasing a football.",
    "CowWithPedestrianCrossing": "A cow and a pedestrian are crossing the road together in front of the vehicle.",
    "CarInOppositeDirection_HIT": "A car from the opposite direction veers into the ego lane, creating an imminent collision risk.",
    "PedestrianAdvesarial_back_STOP": "A pedestrian approaches from behind and suddenly stops in the ego vehicle’s path.",
    "CarForwardParkingWithDoors": "A car is parked ahead with its doors suddenly opening into the lane.",
    "BlinkingYellowIntersection": "The vehicle reaches an intersection with blinking yellow traffic lights requiring caution.",
    "FallenTree": "A large fallen tree is blocking part of the road ahead.",
    "CarWithItem_TRAVELCASE": "A moving car has a travel case loosely attached or placed unsafely on top.",
    "DangerousExcavator": "An excavator swings its arm dangerously close to active traffic lanes.",
    "StaticHighwayAdPole_3": "A tall highway advertisement pole stands close to the roadside, posing a potential hazard.",
    "SuddenSignAheadAndRight": "A sudden road sign indicates a sharp turn ahead to the right.",
    "FootballHighway": "A football rolls across a busy highway, creating a sudden obstacle.",
    "CarForwardStoppingDropoff": "A car ahead abruptly stops to drop off a passenger.",
    "RoadworksWithWorkers_VAN": "Road workers and a parked van partially obstruct the driving lane.",
    "StaticHighwayAdPole_1": "A fixed highway advertisement pole stands near the driving lane.",
    "ShoppingcartRollingDown": "A shopping cart rolls downhill into the roadway.",
    "BusObscuringCar_HIT": "A bus blocks visibility, hiding a car that suddenly emerges into the ego vehicle’s path.",
    "CarWithItem_GUITARCASE": "A car is driving with a guitar case unsecured on its roof.",
    "BusObscuringCar_MISS": "A bus partially blocks the view, and a hidden car narrowly avoids colliding with the ego vehicle.",
    "CarReverseParkingWithDoors": "A car reverses into a parking space while its doors remain open.",
    "CarInOppositeDirection_MISS": "A car from the opposite direction briefly drifts into the ego lane but corrects in time.",
    "WorkerFallingBarrel": "A construction worker drops a barrel that rolls into the roadway.",
    "UnpredictablePedestrianOnPhoneV3": "A pedestrian distracted by their phone changes direction unpredictably near the street.",
    "CarInOppositeDirection_MISTAKE": "A car mistakenly enters the wrong lane facing oncoming traffic.",
    "CarForwardStoppingDropoff_MISS": "A car ahead slows abruptly for a drop-off but resumes driving without causing harm.",
    "PedestrianAdvesarial_front_ENDALL": "A pedestrian intentionally steps directly into the lane from the front, forcing an emergency stop.",
    "StaticCarCrash_1": "A crashed vehicle is stationary on the roadside after an accident.",
    "StaticCarCrash_2": "Two damaged cars remain stopped on the road following a collision.",
    "WorkerFallingWendingMachine": "A worker loses control of a vending machine that falls into the roadway.",
    "EmergencyPlaneLanding": "A small plane makes an emergency landing on a highway ahead.",
    "LooseZooAnimals": "Several zoo animals have escaped and are wandering onto the road.",
    "CarForwardParkingAndReverseNoHarm": "A car ahead attempts to park, reverses briefly, but does not obstruct traffic.",
    "PedestrianAdvesarial_back_LEFTRIGHT": "A pedestrian approaches from behind and suddenly moves left and right unpredictably in the lane.",
    "HaybaleOnHighway": "A hay bale lies in the middle of a highway lane.",
    "SquirrelRunningAcrossTheRoad": "A squirrel suddenly runs across the road in front of the vehicle.",
    "PoliceCarChase_1": "A high-speed police chase passes through the intersection ahead.",
    "PedestrianAdvesarial_front_LEFTRIGHT": "A pedestrian in front of the vehicle moves erratically left and right across the lane.",
    "StaticHighwayAdPole_4": "A fixed highway advertisement pole stands near the edge of the roadway.",
    "StaticHighwayAdPole_2": "A roadside advertisement pole is positioned close to active traffic lanes.",
    "EMSOutgoing": "An emergency medical services vehicle exits a station and merges into traffic.",
    "RunnerInAPark": "A runner jogs across a park path that intersects with the driving route.",
    "BusStopNearPlayground": "A bus stop located next to a playground increases the likelihood of children crossing unexpectedly.",
    "StaticCarCrash_3": "A heavily damaged car remains stalled in the driving lane after an accident.",
    "PedestrianAdvesarial_back_ENDALL": "A pedestrian from behind suddenly blocks the entire lane, forcing the vehicle to halt.",
    "PedestrianAdvesarial_front_STOP": "A pedestrian steps in front of the vehicle and abruptly stops.",
    "StaticEMSObstacle": "A stationary emergency vehicle partially blocks the roadway.",
    "UnpredictableBicycle": "A cyclist swerves unpredictably between lanes.",
    "UnpredictablePedestrianOnPhoneV1": "A pedestrian distracted by a phone drifts into the roadway without awareness.",
    "PoliceCarChase_2": "Multiple police cars pursue a suspect vehicle at high speed through traffic.",
    "RoadworksWithWorkers_NOVAN": "Road workers are performing maintenance on the road without a protective van blocking traffic.",
}


if __name__ == "__main__":
    # IMPORTANT: Set these paths for your environment
    cfg = KeyframeConfig(
        root_dir="/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/day_clear",   # <-- change
        out_dir="/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/keyframes_clip_polished_without_novelty",  # <-- change
        frames_subdir="rgb",  # set None if frames are directly inside scenario folder
        top_k=10,
        mmr_lambda=1.0,
        novelty_weight=0.0,  # set 0.0 to disable novelty
        model_name="ViT-L-14",
        pretrained="openai",
        batch_size=128,
        use_fp16_on_cuda=True,
    )

    select_keyframes_from_scenarios(corner_case_prompts_dict, cfg)
