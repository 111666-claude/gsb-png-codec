"""PNG 读写（8 位 RGB / RGBA）。"""

from .png import PngError, decode, encode

__all__ = ["PngError", "decode", "encode"]
