# Extreme systems laboratories

The load-balancing core performs locked round-robin selection, active health updates,
bounded timeouts and at most one retry—and only for safe methods. It preserves a
request ID across attempts. POST is never replayed automatically.

The microVM planner validates immutable image identity, resource ceilings and an
explicit bridge allow-list before emitting steps. It intentionally does not execute
host commands: Firecracker/KVM setup belongs in a disposable Linux host with a human
reviewing the plan. Together with the capacity scheduler and external agent policy,
these labs expose the key control decisions without pretending the Windows laptop is
a production hypervisor.

