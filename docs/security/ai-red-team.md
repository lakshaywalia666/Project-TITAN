# AI red-team program

The regression suite contains 120 versioned support, prompt-injection and approval
cases. Release candidates must meet quality, citation, latency and cost gates. Test
inputs include malicious retrieved documents, malicious tool output, protected-data
exfiltration attempts, misleading approval wording, unavailable tools and backend
timeouts.

Pattern detection is only a signal. Titan's security boundary is external to the
model: authenticated identity, project/model authorization, fixed capability sets,
typed tool schemas, prohibited actions, exact single-use approvals, egress allow-list,
budgets and audit. The read-only SRE investigator reduces confidence when a telemetry
source is absent and cannot execute remediation.

