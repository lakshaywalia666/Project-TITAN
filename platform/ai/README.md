# Accelerator and model-serving laboratories

These manifests are optional and must not be applied to a non-GPU cluster as part of
the default install. The smoke test teaches device discovery; the vLLM Deployment is
the A10-sized serving path; the KServe object explores managed inference; the Kueue
objects demonstrate quota, admission and queued training.

On the user's GTX 1650, run only small native CUDA/PyTorch experiments. Its 4 GB VRAM
is not an appropriate target for the included vLLM profile. Rent the shown A10 only
for timed experiments, shut it down immediately afterward, and preserve results
locally. No always-on GPU is required for Titan's default offline mode.

