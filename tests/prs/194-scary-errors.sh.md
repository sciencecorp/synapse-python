# CLI error verification

Run `tests/prs/194-scary-errors.sh --device <ip>`. The device-backed cases are
read-only; commands that could change device state fail during parsing or local
validation instead.

- **L1-24** — parses `--device` and help arguments.
- **L26-43** — locates `synapsectl` and creates disposable invalid inputs.
- **L45-90** — runs each case, prints its complete output, and rejects raw
  exception internals or usage text on semantic errors.
- **L92-94** — routes read-only RPC cases through the selected device.
- **L96-104** — checks every ungrouped core command.
- **L106-114** — checks all file, tap, and application subcommands.
- **L116-124** — checks every peripheral build, deploy, and gateware path.
- **L126-128** — checks settings and model deployment commands.
- **L130-132** — prints totals and fails if any message violated the rules.
