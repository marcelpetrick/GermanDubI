"""Application layer: use cases, ports and orchestration.

Depends on :mod:`germandubi.domain` and on the ports it declares. It must never import a
provider implementation; the composition root wires those in.
"""
