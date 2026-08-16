# Reference workloads

Titan Shop is a persistent catalog/order/payment simulator. Prices are looked up
server-side, order creation is idempotent, money is stored as integer paise, and a
versioned explainable fraud scorer runs before payment capture. Review and rejected
orders are never charged.

Titan Support is implemented by the knowledge-plane API: versioned document
ingestion, deterministic chunking, hybrid retrieval, authorization-before-return and
stable citations. The evaluation and agent modules exercise the same contracts.

These workloads are deliberately small. Their purpose is to create realistic
platform failure modes—schema state, duplicate requests, access controls, model
serving, cost and recovery—without paying for a commercial application stack.

