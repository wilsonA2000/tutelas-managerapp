#!/bin/bash
# IURIS — Sesión RunPod completa: bench e2e + iteración 2 LoRA opcional
#
# Pre-requisitos:
#   - Pod RunPod RTX 4090 / A40 con CUDA
#   - Network Volume fair_maroon_coral montado en /workspace
#   - PaddleOCR / Qwen ya descargados de sesión previa
#
# Uso (SSH al pod, pegar este script en /workspace/run.sh):
#   bash run.sh

set -e
WS=/workspace

echo "=== 1. Verificar GPU ==="
nvidia-smi | head -10

echo "=== 2. Compilar llama.cpp con CUDA si no está ==="
if [ ! -f $WS/llama.cpp/build/bin/llama-server ]; then
    cd $WS
    if [ ! -d llama.cpp ]; then
        git clone --depth 1 https://github.com/ggerganov/llama.cpp
    fi
    cd llama.cpp
    cmake -B build -DGGML_CUDA=ON -DGGML_NATIVE=ON 2>&1 | tail -5
    cmake --build build --config Release -j 4 --target llama-server llama-cli 2>&1 | tail -5
fi
ls -lh $WS/llama.cpp/build/bin/llama-server

echo "=== 3. Verificar/Descargar Qwen3 4B base ==="
if [ ! -f $WS/qwen3-4b/Qwen3-4B-Q4_K_M.gguf ]; then
    mkdir -p $WS/qwen3-4b
    cd $WS/qwen3-4b
    python3 -c "from huggingface_hub import hf_hub_download; hf_hub_download('Qwen/Qwen3-4B-GGUF', 'Qwen3-4B-Q4_K_M.gguf', local_dir='.')"
fi

echo "=== 4. Verificar LoRA local ==="
ls -lh $WS/iuris-lora-qwen3-4b.gguf 2>/dev/null || echo "⚠️ Subir LoRA con SCP"
ls -lh $WS/SYSTEM_PROMPT_COMPILER.md 2>/dev/null || echo "⚠️ Subir system prompt"
ls -lh $WS/iuris_lora_dataset_cot.jsonl 2>/dev/null || echo "⚠️ Subir dataset CoT"
ls -lh $WS/tutelas.db 2>/dev/null || echo "⚠️ Subir DB para bench"
ls -lh $WS/bench_end_to_end_local.py 2>/dev/null || echo "⚠️ Subir bench script"

echo "=== 5. Levantar llama-server CUDA con LoRA ==="
pkill -f llama-server 2>/dev/null; sleep 2
nohup $WS/llama.cpp/build/bin/llama-server \
    --model $WS/qwen3-4b/Qwen3-4B-Q4_K_M.gguf \
    --lora $WS/iuris-lora-qwen3-4b.gguf \
    --port 8765 --host 127.0.0.1 \
    --ctx-size 4096 \
    --n-gpu-layers 999 \
    --threads 4 \
    --cache-type-k q8_0 --cache-type-v q8_0 \
    --chat-template chatml \
    > /tmp/llama-server.log 2>&1 &
sleep 10
curl -s http://127.0.0.1:8765/health
echo
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv,noheader

echo "=== 6. Correr bench end-to-end (espera ~5-10 min con GPU) ==="
cd $WS
python3 -u bench_end_to_end_local.py --n-cases 30 2>&1 | tee bench_e2e_results.log

echo "=== 7. Resultados ==="
cat $WS/bench_e2e_local_results.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f\"Global: {d['global_acc_pct']}% ({d['global_correct']}/{d['global_total']})\"); print('Por campo:'); [print(f\"  {k}: {v['acc_pct']}% lat={v['avg_lat_s']}s\") for k,v in d['field_metrics'].items()]"
