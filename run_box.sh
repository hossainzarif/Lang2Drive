# python region_box.py \
#   --root_dir /mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/keyframes_clip_polished \
#   --out_dir  /mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/keyframes_clip_polished/boxes_json \
#   --device cuda \
#   --owl_conf 0.30 \
#   --min_owl_score 0.30 \
#   --sam_ckpt /mnt/beegfs/home/mdzarifhossa2025/mdhossa/VLM_AV/sam_vit_b_01ec64.pth \
#   --sam_type vit_b \

python region_box.py \
  --root_dir /raid/scratch/mdhossa2025/mdhossa/VLM_AV/evaluation_20260909 \
  --out_dir  /raid/scratch/mdhossa2025/mdhossa/VLM_AV/evaluation_final \
  --sam_type vit_b \
  --sam_ckpt /raid/scratch/mdhossa2025/mdhossa/VLM_AV/sam_vit_b_01ec64.pth \
  --device cuda \
  --top_k 3
