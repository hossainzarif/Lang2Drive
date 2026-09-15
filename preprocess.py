# import os
# import shutil
# from pathlib import Path

# ROOT = Path("/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/final")
# IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

# def main():
#     for subfolder in ROOT.iterdir():
#         if not subfolder.is_dir():
#             continue

#         moved = 0
#         # Collect (path, desired_dest_in_subfolder) for all images under subfolder
#         for root, _, files in os.walk(subfolder, topdown=False):
#             root_path = Path(root)
#             if root_path == subfolder:
#                 continue  # skip files already directly in the 5 subfolders

#             for fn in files:
#                 if Path(fn).suffix.lower() in IMG_EXT:
#                     src = root_path / fn
#                     dest = subfolder / fn

#                     if dest.exists() and dest.resolve() != src.resolve():
#                         # avoid overwrite: add prefix from parent folder name
#                         stem, suf = src.stem, src.suffix
#                         dest = subfolder / f"{root_path.name}_{stem}{suf}"
#                         k = 0
#                         while dest.exists():
#                             k += 1
#                             dest = subfolder / f"{root_path.name}_{stem}_{k}{suf}"

#                     if not dest.exists() or dest.resolve() != src.resolve():
#                         shutil.move(str(src), str(dest))
#                         moved += 1
#                         print(f"Moved: {src} -> {dest}")

#         print(f"[{subfolder.name}] moved {moved} images")

# if __name__ == "__main__":
#     main()


# import os
# import json
# import glob
# import random

# # Paths
# GPT_RESPONSE_DIR = "/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/boxes_json/GPT_response"
# OUTPUT_DIR = "/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/CODA-LM/test_subset"

# # Create output directory if it doesn't exist
# os.makedirs(OUTPUT_DIR, exist_ok=True)

# # Fixed questions for each task
# DRIVING_SUGGESTION_QUESTION = "There is an image of traffic captured from the perspective of the ego car. Focus on objects influencing the ego car's driving behavior: vehicles (cars, trucks, buses, etc.), vulnerable road users (pedestrians, cyclists, motorcyclists), traffic signs (no parking, warning, directional, etc.), traffic lights (red, green, yellow), traffic cones, barriers, miscellaneous(debris, dustbin, animals, etc.). You must not discuss any objects beyond the seven categories above. Please provide driving suggestions for the ego car based on the current scene."

# GENERAL_PERCEPTION_QUESTION = "There is an image of traffic captured from the perspective of the ego car. Focus on objects influencing the ego car's driving behavior: vehicles (cars, trucks, buses, etc.), vulnerable road users (pedestrians, cyclists, motorcyclists), traffic signs (no parking, warning, directional, etc.), traffic lights (red, green, yellow), traffic cones, barriers, miscellaneous(debris, dustbin, animals, etc.). You must not discuss any objects beyond the seven categories above. Please describe each object's appearance, position, direction, and explain why it affects the ego car's behavior."

# REGION_PERCEPTION_QUESTION = "Please describe the object inside the red rectangle in the image and explain why it affect ego car driving."


# def find_keyframe_jsons(base_dir, num_per_folder=40):
#     """Find JSON files starting with 'keyframe' from subfolders.
#     Select num_per_folder from each subfolder.
#     """
#     all_jsons = glob.glob(os.path.join(base_dir, "**", "keyframe*.json"), recursive=True)
    
#     # Group by subfolder
#     by_subfolder = {}
#     for path in all_jsons:
#         subfolder = os.path.basename(os.path.dirname(path))
#         if subfolder not in by_subfolder:
#             by_subfolder[subfolder] = []
#         by_subfolder[subfolder].append(path)
    
#     # Select num_per_folder from each subfolder
#     selected = []
#     for subfolder, files in by_subfolder.items():
#         # Randomly select up to num_per_folder files
#         sample_size = min(num_per_folder, len(files))
#         selected.extend(random.sample(files, sample_size))
#         print(f"Selected {sample_size} files from {subfolder} (available: {len(files)})")
    
#     return selected


# def format_general_perception_answer(gp_data):
#     """Format general_perception data into a readable answer string."""
#     parts = []
    
#     if gp_data.get("vehicles"):
#         for v in gp_data["vehicles"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("vulnerable_road_users"):
#         for v in gp_data["vulnerable_road_users"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("traffic_signs"):
#         for v in gp_data["traffic_signs"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("traffic_lights"):
#         for v in gp_data["traffic_lights"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("traffic_cones"):
#         for v in gp_data["traffic_cones"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("barriers"):
#         for v in gp_data["barriers"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     if gp_data.get("other_objects"):
#         for v in gp_data["other_objects"]:
#             parts.append(f"{v['description']} {v['explanation']}")
    
#     return " ".join(parts) if parts else "No significant objects detected."
# def extract_driving_suggestion(data):
#     """Extract driving suggestion from various JSON formats."""
#     if "driving_suggestion" not in data:
#         return ""
    
#     ds = data["driving_suggestion"]
    
#     if not isinstance(ds, dict):
#         return str(ds) if ds else ""
    
#     # Format 1: driving_suggestion.suggestion (direct string)
#     if "suggestion" in ds:
#         return ds["suggestion"]
    
#     # Format 2: driving_suggestion.driving_suggestion.action
#     if "driving_suggestion" in ds:
#         nested = ds["driving_suggestion"]
#         if isinstance(nested, dict):
#             if "action" in nested:
#                 action = nested["action"]
#                 # Some have explanation too - combine them
#                 if "explanation" in nested:
#                     return f"{action} {nested['explanation']}"
#                 return action
#             # Maybe just has explanation
#             if "explanation" in nested:
#                 return nested["explanation"]
#         elif isinstance(nested, str):
#             return nested
    
#     # Format 3: driving_suggestion.action (direct)
#     if "action" in ds:
#         action = ds["action"]
#         if "explanation" in ds:
#             return f"{action} {ds['explanation']}"
#         return action
    
#     # Fallback: try to get any string value
#     for key, value in ds.items():
#         if isinstance(value, str) and value:
#             return value
    
#     return ""

# def json_to_image_path(json_path, base_dir):
#     """Convert JSON path to image path (replace .json with .png)."""
#     # Get relative path from GPT_response folder
#     rel_path = os.path.relpath(json_path, base_dir)
#     # Replace .json with .png
#     image_rel_path = os.path.splitext(rel_path)[0] + ".png"
#     # Format as test/images/<subfolder>/<filename>.png
#     subfolder = os.path.dirname(rel_path)
#     filename = os.path.basename(image_rel_path)
#     return f"test/images/{subfolder}/{filename}"


# def generate_jsonl_files(json_files, base_dir, output_dir):
#     """Generate the 3 JSONL files from selected JSON files."""
    
#     driving_suggestion_data = []
#     general_perception_data = []
#     region_perception_data = []
    
#     question_id = 0
#     region_question_id = 0
    
#     for json_path in json_files:
#         with open(json_path, 'r') as f:
#             data = json.load(f)
        
#         image_path = json_to_image_path(json_path, base_dir)
        
#         # 1. Driving Suggestion - use the new extraction function
#         driving_suggestion = extract_driving_suggestion(data)
        
#         # Skip entries with empty answers if you want
#         # Or keep them and log a warning
#         if not driving_suggestion:
#             print(f"WARNING: No driving suggestion found in {json_path}")
        
#         driving_suggestion_data.append({
#             "question_id": question_id,
#             "image": image_path,
#             "question": DRIVING_SUGGESTION_QUESTION,
#             "answer": driving_suggestion
#         })
        
#         # 2. General Perception
#         general_perception_answer = ""
#         if "general_perception" in data:
#             general_perception_answer = format_general_perception_answer(data["general_perception"])
        
#         general_perception_data.append({
#             "question_id": question_id,
#             "image": image_path,
#             "question": GENERAL_PERCEPTION_QUESTION,
#             "answer": general_perception_answer
#         })
        
#         # 3. Region Perception (multiple entries per image)
#         if "regional_perception" in data:
#             for region_key, region_data in data["regional_perception"].items():
#                 region_answer = region_data.get("description and explanation", "")
#                 # Image path for region perception includes the region number
#                 region_image_path = image_path.replace(".png", f"_object_{region_key}.png")
                
#                 region_perception_data.append({
#                     "question_id": region_question_id,
#                     "image": region_image_path,
#                     "question": REGION_PERCEPTION_QUESTION,
#                     "answer": region_answer
#                 })
#                 region_question_id += 1
        
#         question_id += 1
    
#     # Write JSONL files
#     with open(os.path.join(output_dir, "driving_suggestion.jsonl"), 'w') as f:
#         for item in driving_suggestion_data:
#             f.write(json.dumps(item) + "\n")
    
#     with open(os.path.join(output_dir, "general_perception.jsonl"), 'w') as f:
#         for item in general_perception_data:
#             f.write(json.dumps(item) + "\n")
    
#     with open(os.path.join(output_dir, "region_perception.jsonl"), 'w') as f:
#         for item in region_perception_data:
#             f.write(json.dumps(item) + "\n")
    
#     print(f"Generated {len(driving_suggestion_data)} driving_suggestion entries")
#     print(f"Generated {len(general_perception_data)} general_perception entries")
#     print(f"Generated {len(region_perception_data)} region_perception entries")
#     print(f"Output directory: {output_dir}")


# if __name__ == "__main__":
#     # Set random seed for reproducibility
#     random.seed(42)
    
#     # Find 40 keyframe JSON files PER SUBFOLDER
#     selected_jsons = find_keyframe_jsons(GPT_RESPONSE_DIR, num_per_folder=40)
    
#     print(f"\nTotal selected: {len(selected_jsons)} JSON files")
#     print()
    
#     # Generate the JSONL files
#     generate_jsonl_files(selected_jsons, GPT_RESPONSE_DIR, OUTPUT_DIR)


import json

input_path = "/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/CODA-LM/test_subset/actionable_suggestion.jsonl"
output_path = "/mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/CODA-LM/test_subset/actionable_suggestion.jsonl"

ACTIONABLE_QUESTION = (
    "There is an image of traffic captured from the perspective of the ego car. "
    "Based on the current scene, generate a structured driving action plan for the ego vehicle. "
    "Focus only on objects that influence the ego car's driving behavior, including vehicles (cars, trucks, buses, etc.), "
    "vulnerable road users (pedestrians, cyclists, motorcyclists), traffic signs (no parking, warning, directional, etc.), "
    "traffic lights (red, green, yellow), traffic cones, barriers, and miscellaneous objects (debris, animals, etc.). "
    "Your response must include: 1. Immediate Action (next 1-2 seconds) 2. Short-Term Plan (next 3-5 seconds) "
    "3. Contingency Plan (if unexpected events occur) 4. Primary Hazard (the object posing the highest risk) "
    "5. Risk Level (low, medium, high) with explanation. Return the answer strictly in JSON format."
)

# Read valid JSONL
records = []
with open(input_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            records.append(json.loads(line))

# Update question
for rec in records:
    rec["question"] = ACTIONABLE_QUESTION

# Write back
with open(output_path, "w", encoding="utf-8") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

print(f"Updated {len(records)} records in {output_path}")