# Learning guide

This preview is for seeing a complete, small AI-infrastructure path. It does not count as completing Titan's later AI phases.

## Read the files in this order

1. `README.md` - the purpose and operating sequence.
2. `.env.example` - the values that can change without rewriting the service definition.
3. `compose.yaml` - the desired state of the model-server container.
4. `docs/ARCHITECTURE.md` - how the pieces communicate and where the trust boundary sits.
5. `scripts/check-host.sh` - evidence required before starting.
6. `scripts/start.sh` - image pull and service startup.
7. `requests/chat-request.json` - the data sent to the API.
8. `scripts/test-api.sh` - the two HTTP requests used as proof.
9. `scripts/stop.sh` and `docs/COST-AND-SAFETY.md` - shutdown and billing safety.

## Vocabulary

- **GPU host:** the rented Linux machine containing the A10.
- **Image:** a packaged filesystem and program definition used to create a container.
- **Container:** the running model-server process and its isolated environment.
- **Model:** the weights and configuration that generate output tokens.
- **Model server:** software that loads the model and handles concurrent inference requests.
- **API:** the HTTP contract clients use to send requests and receive responses.
- **VRAM:** GPU memory used for model weights and inference state.
- **Volume:** persistent Docker-managed storage used here for the model download cache.

## Questions you must answer before renting the GPU

1. Why does `compose.yaml` publish port 8000 on `127.0.0.1` instead of `0.0.0.0`?
2. What is the difference between the Docker image, the container, vLLM, and the Qwen model?
3. Why is the model cache stored in a named volume?
4. What evidence proves that the model is using the GPU?
5. Why is `docker compose down` insufficient to guarantee billing has stopped?

Do not memorize the answers. Trace each answer to a specific line or comment in the files.

