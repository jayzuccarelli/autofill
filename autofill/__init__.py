"""AI-powered form autofill assistant."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("autofill")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
