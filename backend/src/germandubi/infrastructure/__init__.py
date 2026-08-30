"""Infrastructure layer: adapters that implement application ports.

Nothing imports *from* this package except the composition root: the API's dependency
wiring, the worker runner and the CLI. That rule is what keeps the domain and application
layers free of FFmpeg, SQLAlchemy and provider SDKs.
"""
