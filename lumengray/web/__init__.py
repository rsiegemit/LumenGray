"""LumenGray web app: a browser UI over the photostack pipeline."""

from .server import app, create_app

__all__ = ["app", "create_app"]
