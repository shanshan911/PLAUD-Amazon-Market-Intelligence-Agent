# Codex Collaboration Notes

- The user prefers maximum autonomy in this project: proceed with implementation, inspection, local testing, localhost checks, and routine file edits without asking first when the requested goal is clear.
- Prefer running low-risk local checks directly in the workspace, such as file inspection, tests, localhost health checks, and local dev server commands.
- When a low-risk command still requires escalated approval, request it with a narrow reusable `prefix_rule` so the user can approve the command category once instead of clicking repeatedly.
- Good reusable prefixes for this project include the bundled Python test or platform commands, local `curl` checks against `127.0.0.1:8501`, and project scripts under `scripts/`.
- Keep destructive actions, external network access, dependency installation, credential access, and broad filesystem writes as explicit one-off confirmations.
