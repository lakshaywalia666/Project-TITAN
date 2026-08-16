# Optional production-data laboratory

Titan's default runtime uses SQLite because it is correct for one laptop and costs
nothing. `compose.data.yaml` provides isolated PostgreSQL, Redis, Redpanda and MinIO
profiles for learning production data behavior without making them prerequisites.

Run only one profile at a time on the 8 GB machine:

```bash
docker compose -f compose.data.yaml --profile relational up -d
docker compose -f compose.data.yaml --profile cache up -d
docker compose -f compose.data.yaml --profile streaming up -d
docker compose -f compose.data.yaml --profile object up -d
```

PostgreSQL is authoritative relational state; Redis may only cache reconstructable
data; Redpanda is an at-least-once event transport requiring idempotent consumers;
MinIO stores versioned blobs referenced by metadata. The application must remain
correct when Redis is empty and when an event is delivered twice.

Secrets belong in an ignored `.env`, never in the Compose file. These services bind
only to loopback and are not a security-hardened Internet deployment.

