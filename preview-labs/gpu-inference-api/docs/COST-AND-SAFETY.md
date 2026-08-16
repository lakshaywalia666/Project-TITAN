# Cost and safety guard

The supplied screenshot shows a compute price of **INR 29.62 per hour**. Verify the live provider price, storage rules, taxes, and instance state before starting because the screenshot is not a billing guarantee.

Approximate compute-only cost at that displayed rate:

| Runtime | Approximate cost |
|---:|---:|
| 30 minutes | INR 14.81 |
| 1 hour | INR 29.62 |
| 90 minutes | INR 44.43 |
| 2 hours | INR 59.24 |
| 10 hours | INR 296.20 |

## Session budget

- Target one session of no more than 90 minutes.
- Set a phone timer before creating the instance.
- Record the creation time and provider instance ID.
- Keep the API private; do not open port 8000 to the Internet.
- Do not place cloud credentials or private data in prompts.
- Use only the small public model configured in `.env.example`.
- Stop the container after the test.
- Stop or terminate the provider instance separately.
- Reopen the provider console and verify that the instance is no longer running.

Stopping Docker does **not** necessarily stop infrastructure billing.

## Evidence to save before termination

- Output of `nvidia-smi`
- Successful `/v1/models` response
- Successful chat response
- One screenshot of GPU utilization during a request
- Start and stop timestamps
- Final provider status showing the instance stopped or terminated

