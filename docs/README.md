# GermanDubI documentation

The repository root contains only the files that GitHub, contributors, and automation
expect to find immediately. Detailed product and engineering material lives here.

| Area | Contents |
| --- | --- |
| [`product/`](product/) | Product vision and target architecture. |
| [`project/`](project/) | The committed execution plan and unresolved design questions. |
| [`architecture/`](architecture/) | The concise C4 view of the implemented system. |
| [`adr/`](adr/) | Accepted architecture decisions that are expensive to reverse. |
| [`development/`](development/) | Workstation setup and the development workflow. |
| [`operations/`](operations/) | Running, troubleshooting, releasing, and containerising GermanDubI. |
| [`benchmarks/`](benchmarks/) | Reproducible real-provider measurements and their context. |
| [`reviews/`](reviews/) | Point-in-time repository reviews retained as historical evidence. |

Start with the [product vision](product/vision.md) for intent, the
[C4 architecture](architecture/c4.md) for the current implementation, and the
[development guide](development/getting-started.md) to run the project. To run it without
installing a toolchain at all, see [operations/docker.md](operations/docker.md).

The following conventional entry points intentionally remain at the repository root:
`README.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `SECURITY.md`, and `AGENTS.md`.
