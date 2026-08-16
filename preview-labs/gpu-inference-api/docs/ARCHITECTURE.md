# Architecture

```text
Laptop
  |
  | SSH tunnel (port 8000)
  v
Rented GPU server: 127.0.0.1:8000
  |
  v
Docker container
  |
  v
vLLM model server
  |
  +-- OpenAI-compatible HTTP API
  +-- Qwen model loaded into A10 VRAM
  +-- model files cached in a Docker volume
```

## Trust boundary

The API is bound to `127.0.0.1`, so it is not intentionally exposed to the public Internet. A user reaches it through an authenticated SSH connection or runs the test directly on the server.

The API token is still required because protection should be layered. This is a learning token, not a production secret-management design.

## Component responsibilities

- Docker starts and isolates the process.
- The NVIDIA container integration gives the container controlled GPU access.
- vLLM loads the model and converts HTTP requests into GPU inference work.
- The model generates tokens; it does not create the network API itself.
- The named Docker volume caches downloaded model files between container restarts.
- The cloud provider controls the machine lifecycle and billing.

