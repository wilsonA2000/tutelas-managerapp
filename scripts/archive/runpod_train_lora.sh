#!/bin/bash
# IURIS LoRA Training en RunPod — Qwen3 4B + Unsloth
# =====================================================
# Pipeline completo: setup + train + export + GGUF + download
#
# PRE-REQUISITOS EN RUNPOD:
#   - Pod template: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
#   - GPU: RTX 4090 24GB ($0.34/hr) o A40 48GB ($0.39/hr) — 4090 es suficiente
#   - Disk: 50GB volume
#
# USO:
#   1. Spin up pod RunPod con specs arriba
#   2. Conectar via web terminal o SSH
#   3. Subir dataset al pod (ver RUNPOD_SETUP.md)
#   4. Pegar este script en /workspace/train.sh: chmod +x train.sh && bash train.sh
#
# OUTPUT FINAL:
#   - /workspace/iuris-lora-qwen3-4b/                    (HF format, para reentrenar)
#   - /workspace/iuris-lora-qwen3-4b.gguf                (GGUF, para llama-server)
#   - /workspace/iuris-lora-qwen3-4b.tar.gz              (todo empaquetado)
#
# TIEMPO: 60-120 min para 2326 ejemplos × 3 epochs en RTX 4090
# COSTO:  ~$0.40-0.80 USD

set -euo pipefail

WORKSPACE="${WORKSPACE:-/workspace}"
DATASET="${DATASET:-$WORKSPACE/iuris_lora_dataset.jsonl}"
VAL_DATASET="${VAL_DATASET:-$WORKSPACE/iuris_lora_dataset_val.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-$WORKSPACE/iuris-lora-qwen3-4b}"
BASE_MODEL="${BASE_MODEL:-Qwen/Qwen3-4B}"
EPOCHS="${EPOCHS:-3}"
LR="${LR:-2e-4}"
BATCH="${BATCH:-2}"          # 2 con grad accum 4 = effective batch 8
GRAD_ACCUM="${GRAD_ACCUM:-4}"
MAX_LEN="${MAX_LEN:-2048}"
LORA_R="${LORA_R:-16}"
LORA_ALPHA="${LORA_ALPHA:-32}"

echo "=================================================="
echo "  IURIS LoRA Training — Qwen3 4B"
echo "=================================================="
echo "  Workspace:    $WORKSPACE"
echo "  Dataset:      $DATASET"
echo "  Base model:   $BASE_MODEL"
echo "  Output:       $OUTPUT_DIR"
echo "  Epochs:       $EPOCHS"
echo "  Batch:        $BATCH × grad_accum $GRAD_ACCUM = $((BATCH*GRAD_ACCUM)) effective"
echo "  Max seq len:  $MAX_LEN"
echo "  LoRA r/alpha: $LORA_R / $LORA_ALPHA"
echo "=================================================="

# 1. Verify GPU
echo "→ Verificando GPU..."
nvidia-smi || { echo "❌ GPU no disponible"; exit 1; }
GPU_MEM=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
echo "  GPU RAM: ${GPU_MEM} MB"

# 2. Verify dataset
echo "→ Verificando dataset..."
if [[ ! -f "$DATASET" ]]; then
    echo "❌ Dataset no encontrado en $DATASET"
    echo "   Subí el archivo iuris_lora_dataset.jsonl al pod primero."
    echo "   Ver RUNPOD_SETUP.md sección 'Subir dataset'"
    exit 1
fi
N_TRAIN=$(wc -l < "$DATASET")
[[ -f "$VAL_DATASET" ]] && N_VAL=$(wc -l < "$VAL_DATASET") || N_VAL=0
echo "  ✓ $N_TRAIN ejemplos train, $N_VAL val"

# 3. Install dependencies (Unsloth = LoRA optimizado)
echo "→ Instalando deps (5-10 min)..."
pip install -q --upgrade pip
# Unsloth provee kernels custom 2-5x más rápidos que TRL puro para LoRA
pip install -q "unsloth[colab-new] @ git+https://github.com/unslothai/unsloth.git"
pip install -q --no-deps trl peft accelerate bitsandbytes
pip install -q xformers

# 4. Login HuggingFace (solo si necesitamos repos privados)
if [[ -n "${HF_TOKEN:-}" ]]; then
    huggingface-cli login --token "$HF_TOKEN" --add-to-git-credential || true
fi

# 5. Generate training script
cat > "$WORKSPACE/train.py" << 'PYEOF'
"""IURIS LoRA training sobre Qwen3 4B con Unsloth (kernels optimizados)."""
import json
import os
from pathlib import Path

import torch
from datasets import load_dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig

# Config desde env
DATASET = os.environ.get("DATASET", "/workspace/iuris_lora_dataset.jsonl")
VAL_DATASET = os.environ.get("VAL_DATASET", "/workspace/iuris_lora_dataset_val.jsonl")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/workspace/iuris-lora-qwen3-4b")
BASE_MODEL = os.environ.get("BASE_MODEL", "Qwen/Qwen3-4B")
EPOCHS = int(os.environ.get("EPOCHS", "3"))
LR = float(os.environ.get("LR", "2e-4"))
BATCH = int(os.environ.get("BATCH", "2"))
GRAD_ACCUM = int(os.environ.get("GRAD_ACCUM", "4"))
MAX_LEN = int(os.environ.get("MAX_LEN", "2048"))
LORA_R = int(os.environ.get("LORA_R", "16"))
LORA_ALPHA = int(os.environ.get("LORA_ALPHA", "32"))

print(f"→ Cargando {BASE_MODEL} en 4-bit...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_LEN,
    dtype=None,                  # auto bfloat16 si soportado
    load_in_4bit=True,           # QLoRA 4-bit
)
print(f"  ✓ modelo cargado")

# Aplica LoRA (PEFT via Unsloth)
model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_R,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=LORA_ALPHA,
    lora_dropout=0,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
    use_rslora=False,
    loftq_config=None,
)
model.print_trainable_parameters()

# Carga dataset y formatea para Qwen3 ChatML
def fmt_qwen3(ex):
    """Aplica chat template Qwen3."""
    text = tokenizer.apply_chat_template(
        ex["messages"],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}

print(f"→ Cargando dataset...")
train_ds = load_dataset("json", data_files=DATASET, split="train").map(fmt_qwen3)
val_ds = (load_dataset("json", data_files=VAL_DATASET, split="train").map(fmt_qwen3)
          if Path(VAL_DATASET).exists() else None)
print(f"  ✓ train: {len(train_ds)} | val: {len(val_ds) if val_ds else 0}")

# Training config
sft_config = SFTConfig(
    output_dir=OUTPUT_DIR,
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH,
    gradient_accumulation_steps=GRAD_ACCUM,
    learning_rate=LR,
    weight_decay=0.01,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",
    logging_steps=10,
    save_strategy="epoch",
    save_total_limit=2,
    eval_strategy="epoch" if val_ds else "no",
    bf16=torch.cuda.is_bf16_supported(),
    fp16=not torch.cuda.is_bf16_supported(),
    optim="adamw_8bit",
    max_seq_length=MAX_LEN,
    dataset_text_field="text",
    packing=False,                # más predictible para validación
    report_to="none",
    seed=42,
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    args=sft_config,
)

print("→ Iniciando training...")
trainer_stats = trainer.train()
print(f"\n✓ Training completado:")
print(f"  steps: {trainer_stats.global_step}")
print(f"  loss final: {trainer_stats.training_loss:.4f}")

print(f"\n→ Guardando adapter LoRA...")
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

# Export GGUF para llama-server warm
print(f"\n→ Exportando GGUF para llama-server...")
try:
    model.save_pretrained_gguf(
        OUTPUT_DIR + "_gguf",
        tokenizer,
        quantization_method="q4_k_m",
    )
    print(f"  ✓ GGUF: {OUTPUT_DIR}_gguf/")
except Exception as e:
    print(f"  ⚠️ GGUF export falló: {e}")
    print(f"     Adapter HF queda en {OUTPUT_DIR}, podés convertir manualmente luego.")

print("\n" + "="*50)
print("✓ LISTO")
print("="*50)
print(f"  HF adapter: {OUTPUT_DIR}")
print(f"  GGUF (si OK): {OUTPUT_DIR}_gguf")
PYEOF

# 6. Run training
echo "→ Lanzando training... (60-120 min en RTX 4090)"
export DATASET VAL_DATASET OUTPUT_DIR BASE_MODEL EPOCHS LR BATCH GRAD_ACCUM MAX_LEN LORA_R LORA_ALPHA
python3 "$WORKSPACE/train.py" 2>&1 | tee "$WORKSPACE/train.log"

# 7. Pack output for download
echo "→ Empaquetando para descarga..."
cd "$WORKSPACE"
TARBALL="iuris-lora-qwen3-4b.tar.gz"
tar czf "$TARBALL" $(basename "$OUTPUT_DIR") $(basename "$OUTPUT_DIR")_gguf 2>/dev/null || \
    tar czf "$TARBALL" $(basename "$OUTPUT_DIR")
ls -lh "$TARBALL"

echo
echo "=================================================="
echo "  ✓ TRAINING COMPLETADO"
echo "=================================================="
echo
echo "Para descargar al local:"
echo "  scp -P <pod_port> root@<pod_ip>:$WORKSPACE/$TARBALL ."
echo
echo "Para subir a HuggingFace privado (recomendado):"
echo "  huggingface-cli upload <user>/iuris-lora-qwen3-4b $OUTPUT_DIR"
echo "  huggingface-cli upload <user>/iuris-lora-qwen3-4b-gguf ${OUTPUT_DIR}_gguf"
echo
echo "Próximo paso: cargar el GGUF en llama-server local con --lora flag"
