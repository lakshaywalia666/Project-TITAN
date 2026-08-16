# Capacity, tenancy and FinOps

Titan treats quota as admission control, not an after-the-fact billing report. The
capacity planner rejects work before placement when a tenant would exceed CPU,
memory or GPU entitlement. Accelerator class is a hard constraint. Bin-packing
reduces active nodes; spreading improves failure isolation.

The control-plane usage ledger aggregates resource metrics, and the AI gateway
reserves token budget before a model call. The portal displays both. Cloud labs must
carry owner, project, expiry and cost-center tags, and GPU experiments must have an
explicit shutdown time.

