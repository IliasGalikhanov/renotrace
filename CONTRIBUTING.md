# Development agreement

The planning chat defines the next task and acceptance criteria. The implementation chat completes that scope and stops before the next stage.

For every future development task, write and run meaningful functionality tests even when the task does not repeat this requirement. Exercise success, relevant failures, and domain invariants; do not count compilation or a screenshot as proof of financial behavior. Report exact commands, results, and limitations.

Commit completed changes with a meaningful message and push when access is available. Never report a push as completed unless the remote confirms it. Do not overwrite unrelated work or force-push.

Financial rules: integer cents, explicit unknowns, deterministic arithmetic, separate payment requests and calculated balances, evidence references, and no AI/network/database dependencies in the ledger package.
