"""Live Football Manager queries and explicit stored training selection editing."""

__version__ = "0.175.0"

# On a game build other than the pinned one, rewrite the plugin addresses of every module of
# the package as it loads (address_book.py); on the pinned build this does nothing.
from . import address_book as _address_book  # noqa: E402

_address_book.install_from_environment()

