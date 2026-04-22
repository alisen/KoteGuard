"""KoteGuard – safe Copilot agent sandboxing for mobile developers."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__ = _pkg_version("koteguard")
except PackageNotFoundError:
    # Running from source without being installed
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
