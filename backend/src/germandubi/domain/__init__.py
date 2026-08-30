"""Pure domain model.

This package depends on the Python standard library only. It must never import FastAPI,
SQLAlchemy, Pydantic, ``yt-dlp``, FFmpeg or any provider SDK. The rule is enforced by
``backend/tests/unit/test_architecture.py``.
"""
