# from openai import OpenAI
# client = OpenAI()


# path='/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/keyframes_clip_polished/boxes_json/overlays'
# response = client.responses.create(
#     model="gpt-4o-mini",
#     input=[
#         {
#             "role": "user",
#             "content": [
#                 {
#                     "type": "input_text",
#                     "text": "What teams are playing in this image?",
#                 },
#                 {
#                     "type": "input_image",
#                     "image_url": "https://api.nga.gov/iiif/a2e6da57-3cd1-4235-b20e-95dcaefed6c8/full/!800,800/0/default.jpg"
#                 }
#             ]
#         }
#     ]
# )

# print(response.output_text)


import argparse
import base64
import json
import mimetypes
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from openai import OpenAI
from tqdm import tqdm


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class Prompts:
    system: str
    general_perception: str
    regional_perception: str
    actionable_suggestion: str


def load_prompts(prompts_path: Path) -> Prompts:
    with prompts_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    required = ["system", "general_perception", "regional_perception", "actionable_suggestion"]
    missing = [k for k in required if k not in data or not isinstance(data[k], str) or not data[k].strip()]
    if missing:
        raise ValueError(f"{prompts_path} is missing keys or has empty strings: {missing}")

    return Prompts(
        system=data["system"].strip(),
        general_perception=data["general_perception"].strip(),
        regional_perception=data["regional_perception"].strip(),
        actionable_suggestion=data["actionable_suggestion"].strip(),
    )


def image_to_data_url(image_path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(image_path))
    if mime is None:
        # Default fallback; most of your dataset will still be jpg/png
        mime = "application/octet-stream"

    raw = image_path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def safe_json_loads(s: str) -> Tuple[Optional[Any], Optional[str]]:
    try:
        return json.loads(s), None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def call_with_retries(fn, max_retries: int = 6, base_sleep: float = 1.0):
    """
    Simple exponential backoff with jitter for transient API failures / rate limits.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt >= max_retries:
                raise
            sleep = base_sleep * (2 ** attempt) + random.uniform(0, 0.25)
            time.sleep(sleep)


def run_one_prompt(
    client: OpenAI,
    model: str,
    system_prompt: str,
    user_prompt: str,
    image_data_url: str,
    temperature: float,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "raw_text": "...",
        "json": {...} | None,
        "json_error": "... | None"
      }
    """
    def _do():
        # Responses API: image input supported via base64 data URL :contentReference[oaicite:2]{index=2}
        # Force JSON output using text.format :contentReference[oaicite:3]{index=3}
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_prompt},
                        {"type": "input_image", "image_url": image_data_url},
                    ],
                },
            ],
            temperature=temperature,
            text={"format": {"type": "json_object"}},
        )
        raw_text = getattr(resp, "output_text", None) or ""
        print(raw_text)
        return raw_text

    raw_text = call_with_retries(_do)

    parsed, err = safe_json_loads(raw_text)
    return {"raw_text": raw_text, "json": parsed, "json_error": err}


def iter_images(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
            yield p


def ensure_parent_dir(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input_dir", type=str, required=True, help="Root folder like boxes_json/")
    ap.add_argument("--output_dir", type=str, required=True, help="Root folder like GPT_response/")
    ap.add_argument("--prompts", type=str, required=True, help="Path like VLM_AV/prompts.json")
    ap.add_argument("--model", type=str, default=os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
    ap.add_argument("--overwrite", action="store_true", help="Overwrite existing output JSONs")
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    prompts_path = Path(args.prompts).resolve()

    if not input_dir.exists():
        raise FileNotFoundError(f"input_dir not found: {input_dir}")
    if not prompts_path.exists():
        raise FileNotFoundError(f"prompts.json not found: {prompts_path}")

    prompts = load_prompts(prompts_path)
    client = OpenAI()

    images = list(iter_images(input_dir))
    if not images:
        print(f"No images found under: {input_dir}")
        return

    for img_path in tqdm(images, desc="Annotating images"):
        rel = img_path.relative_to(input_dir)
        out_path = (output_dir / rel).with_suffix(".json")
        ensure_parent_dir(out_path)

        if out_path.exists() and not args.overwrite:
            continue

        # Encode once, reuse for all 3 calls
        image_data_url = image_to_data_url(img_path)

        general = run_one_prompt(
            client=client,
            model=args.model,
            system_prompt=prompts.system,
            user_prompt=prompts.general_perception,
            image_data_url=image_data_url,
            temperature=args.temperature,
        )

        regional = run_one_prompt(
            client=client,
            model=args.model,
            system_prompt=prompts.system,
            user_prompt=prompts.regional_perception,
            image_data_url=image_data_url,
            temperature=args.temperature,
        )

        actionable = run_one_prompt(
            client=client,
            model=args.model,
            system_prompt=prompts.system,
            user_prompt=prompts.actionable_suggestion,
            image_data_url=image_data_url,
            temperature=args.temperature,
        )

        payload = {
            "meta": {
                "image_path": str(rel).replace("\\", "/"),
                "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                "model": args.model,
                "temperature": args.temperature,
                "prompts_file": str(prompts_path),
            },
            "general_perception": general["json"] if general["json"] is not None else general["raw_text"],
            "regional_perception": regional["json"] if regional["json"] is not None else regional["raw_text"],
            "actionable_suggestion": actionable["json"] if actionable["json"] is not None else actionable["raw_text"],
            # Keep debugging info if parsing failed
            "parse_debug": {
                "general_json_error": general["json_error"],
                "regional_json_error": regional["json_error"],
                "actionable_json_error": actionable["json_error"],
            },
        }

        with out_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Done. Outputs saved under: {output_dir}")


if __name__ == "__main__":
    main()
