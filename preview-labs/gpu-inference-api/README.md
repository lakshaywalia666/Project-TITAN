# Titan GPU Inference Preview

This is a short, provider-independent learning lab for serving a small language model on one NVIDIA A10 GPU. It demonstrates the path from a rented Linux host to a private HTTP API without building the rest of Titan first.

## What this lab teaches

- host and GPU prerequisite checks;
- containerized GPU access;
- model download and VRAM loading;
- an OpenAI-compatible model API;
- localhost-only network exposure;
- a repeatable smoke test;
- logs, GPU observation, shutdown and cost discipline.

## What this lab does not claim

- production security or high availability;
- Kubernetes deployment;
- model quality evaluation;
- autoscaling or multi-GPU inference;
- completion of Titan's AI-platform phases.

## Files

```text
gpu-inference-api/
|-- .env.example
|-- compose.yaml
|-- requests/
|   `-- chat-request.json
|-- scripts/
|   |-- check-host.sh
|   |-- start.sh
|   |-- test-api.sh
|   `-- stop.sh
`-- docs/
    |-- ARCHITECTURE.md
    |-- COST-AND-SAFETY.md
    `-- LEARNING-GUIDE.md
```

## Do not rent the GPU yet

First read `docs/LEARNING-GUIDE.md` and answer its five questions. The paid instance should start only after the files and shutdown procedure make sense.

## Planned run sequence

These commands are for a later supervised session on the rented Ubuntu GPU server:

```bash
cp .env.example .env
# Edit .env and replace API_KEY with a long random learning token.

chmod +x scripts/*.sh
./scripts/check-host.sh
./scripts/start.sh
docker compose logs -f model-server
```

After the server reports that it is ready, use a second SSH session:

```bash
./scripts/test-api.sh
watch -n 1 nvidia-smi
```

When finished:

```bash
./scripts/stop.sh
```

Then stop or terminate the GPU machine in the provider console and verify its final state. Stopping the container alone does not stop infrastructure billing.

## Optional access from the laptop

Do not open port 8000 publicly. Use an SSH tunnel from the laptop:

```bash
ssh -L 8000:127.0.0.1:8000 USER@GPU_SERVER_IP
```

While that SSH connection remains open, the laptop can reach `http://127.0.0.1:8000`.

## Primary references

- [vLLM GPU installation and official container](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [vLLM OpenAI-compatible server](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
- [Qwen model organization](https://huggingface.co/Qwen)

