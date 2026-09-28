"""PNG 读写（8 位 RGB / RGBA），只用标准库。

缺陷：写入时只用一个 IDAT、filter 固定 0、分块 CRC 全写 0；
读取时不校验 CRC、IDAT 只取第一块、只支持 filter 0。
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"

CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


class PngError(ValueError):
    """PNG 不合法。缺陷：不带字节偏移。"""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def _channels(color_type):
    if color_type not in CHANNELS:
        raise PngError("不支持的颜色类型：%d" % color_type)
    return CHANNELS[color_type]


def _chunk(kind, payload):
    """打包一个 PNG 分块。缺陷：CRC 直接写 0。"""
    return struct.pack(">I", len(payload)) + kind + payload + b"\x00\x00\x00\x00"


def encode(width, height, pixels, color_type=2):
    """把像素编成 PNG。缺陷：整张图只用一个 IDAT、filter 固定 0、CRC 全是 0。"""
    channels = _channels(color_type)
    stride = width * channels
    if width <= 0 or height <= 0 or len(pixels) != stride * height:
        raise PngError("像素数量与尺寸不匹配")
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # 缺陷：filter 固定 0
        raw.extend(pixels[row * stride:(row + 1) * stride])
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    return (SIGNATURE + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(raw)))
            + _chunk(b"IEND", b""))


def split_chunks(data):
    """把文件切成 (类型, 数据) 列表。缺陷：不校验签名之外的任何东西，也没有偏移信息。"""
    if not data.startswith(SIGNATURE):
        raise PngError("不是 PNG 文件")
    offset = len(SIGNATURE)
    chunks = []
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if len(payload) != length:
            raise PngError("分块长度超出文件")
        chunks.append((kind, payload))
        offset += 12 + length
    return chunks


def decode(data):
    """解码 PNG。缺陷：IDAT 只取第一块，filter 只支持 0，CRC 不校验。"""
    chunks = split_chunks(data)
    header = None
    idat = b""
    idat_chunks = 0
    for kind, payload in chunks:
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", payload)
        elif kind == b"IDAT":
            idat_chunks += 1
            if not idat:
                idat = payload  # 缺陷：后面的 IDAT 全丢掉
        elif kind == b"IEND":
            break
    if header is None:
        raise PngError("缺少 IHDR")
    width, height, depth, color_type, compression, filter_method, interlace = header
    if depth != 8 or compression != 0 or filter_method != 0 or interlace != 0:
        raise PngError("只支持 8 位非隔行 PNG")
    channels = _channels(color_type)
    stride = width * channels
    raw = zlib.decompress(idat)
    out = bytearray()
    at = 0
    for _ in range(height):
        if at >= len(raw):
            raise PngError("像素数据不完整")
        filter_type = raw[at]
        at += 1
        if filter_type != 0:
            raise PngError("只支持 filter 0")  # 缺陷
        line = raw[at:at + stride]
        if len(line) != stride:
            raise PngError("像素数据不完整")
        at += stride
        out.extend(line)
    return {
        "width": width,
        "height": height,
        "color_type": color_type,
        "pixels": bytes(out),
        "idat_chunks": idat_chunks,
    }
