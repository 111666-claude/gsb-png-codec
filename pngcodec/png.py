"""PNG 读写（8 位 RGB / RGBA），只用标准库。

写入：逐行自适应 filter（0..4 中选编码后字节绝对值之和最小的一种），
单个 IDAT 载荷上限 8192 字节、超出拆成多块，每个分块的 CRC32 都写对。
读取：校验签名与每个分块的 CRC（坏 CRC 报错并给分块偏移），把所有 IDAT
按顺序拼接后再解压，按 5 种 filter 反过滤；缺 IEND、IHDR 不是第一块、
分块长度超出文件等结构问题一律报错。
"""

import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"

CHANNELS = {2: 3, 6: 4}

IDAT_LIMIT = 8192


class PngError(ValueError):
    """PNG 不合法；message 里带出错位置（字节偏移）。"""

    def __init__(self, message, offset=None):
        if offset is not None:
            message = "%s（偏移 %d）" % (message, offset)
        super().__init__(message)
        self.message = message
        self.offset = offset


def _channels(color_type):
    if color_type not in CHANNELS:
        raise PngError("不支持的颜色类型：%d（仅支持 2=RGB 与 6=RGBA）" % color_type)
    return CHANNELS[color_type]


def _chunk(kind, payload):
    """打包一个 PNG 分块，CRC32 覆盖类型与数据。"""
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def _paeth(a, b, c):
    estimate = a + b - c
    pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(filter_type, line, previous, bpp):
    """按指定 filter 编码一行，previous 为上一行原始像素（首行为 None）。"""
    if filter_type == 0:
        return bytes(line)
    out = bytearray(len(line))
    for index, value in enumerate(line):
        left = line[index - bpp] if index >= bpp else 0
        up = previous[index] if previous is not None else 0
        up_left = previous[index - bpp] if previous is not None and index >= bpp else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        else:
            predictor = _paeth(left, up, up_left)
        out[index] = (value - predictor) & 0xFF
    return bytes(out)


def _score(filtered):
    """编码后字节按有符号解释的绝对值之和。"""
    return sum(byte if byte < 128 else 256 - byte for byte in filtered)


def _best_filter(line, previous, bpp):
    """在 0..4 号 filter 里选绝对值之和最小的一种（并列取小号）。"""
    best_type = 0
    best_row = bytes(line)
    best_score = _score(best_row)
    for filter_type in (1, 2, 3, 4):
        filtered = _filter_row(filter_type, line, previous, bpp)
        score = _score(filtered)
        if score < best_score:
            best_type, best_row, best_score = filter_type, filtered, score
    return best_type, best_row


def encode(width, height, pixels, color_type=2):
    """把像素编成 PNG：逐行自适应 filter，IDAT 载荷不超 8192 字节，CRC 写对。

    单遍处理，内存 O(一行 + 一个分块)：压缩用流式 compressobj，
    凑满 8192 字节就落一个 IDAT 分块。
    """
    channels = _channels(color_type)
    stride = width * channels
    if width <= 0 or height <= 0 or len(pixels) != stride * height:
        raise PngError("像素数量与尺寸不匹配")
    header = struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0)
    out = bytearray()
    out += SIGNATURE
    out += _chunk(b"IHDR", header)
    compressor = zlib.compressobj()
    pending = bytearray()
    previous = None
    for row in range(height):
        line = pixels[row * stride:(row + 1) * stride]
        filter_type, filtered = _best_filter(line, previous, channels)
        pending += compressor.compress(bytes([filter_type]) + filtered)
        while len(pending) >= IDAT_LIMIT:
            out += _chunk(b"IDAT", bytes(pending[:IDAT_LIMIT]))
            del pending[:IDAT_LIMIT]
        previous = line
    pending += compressor.flush()
    while pending:
        out += _chunk(b"IDAT", bytes(pending[:IDAT_LIMIT]))
        del pending[:IDAT_LIMIT]
    out += _chunk(b"IEND", b"")
    return bytes(out)


def split_chunks(data, verify_crc=True):
    """把文件切成 (类型, 数据) 列表；校验签名、分块长度与 CRC，错误带偏移。"""
    if not data.startswith(SIGNATURE):
        raise PngError("不是 PNG 文件", 0)
    offset = len(SIGNATURE)
    chunks = []
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        if offset + 12 + length > len(data):
            raise PngError("分块长度超出文件", offset)
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        if verify_crc:
            stored = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
            if zlib.crc32(kind + payload) & 0xFFFFFFFF != stored:
                raise PngError("分块 %s 的 CRC 校验失败" % kind.decode("latin1"), offset)
        chunks.append((kind, payload))
        offset += 12 + length
    if offset != len(data):
        raise PngError("文件尾部有残缺分块", offset)
    return chunks


def _unfilter_row(filter_type, line, previous, bpp):
    """按指定 filter 还原一行，previous 为上一行重建后的字节（首行为 None）。"""
    out = bytearray(line)
    if filter_type == 0:
        return bytes(out)
    for index in range(len(out)):
        left = out[index - bpp] if index >= bpp else 0
        up = previous[index] if previous is not None else 0
        up_left = previous[index - bpp] if previous is not None and index >= bpp else 0
        if filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        else:
            predictor = _paeth(left, up, up_left)
        out[index] = (out[index] + predictor) & 0xFF
    return bytes(out)


def decode(data):
    """解码 PNG：校验结构，拼接全部 IDAT，按 5 种 filter 反过滤。"""
    chunks = split_chunks(data)
    if not chunks or chunks[0][0] != b"IHDR":
        raise PngError("IHDR 必须是第一个分块")
    ihdr = chunks[0][1]
    if len(ihdr) != 13:
        raise PngError("IHDR 长度必须是 13 字节")
    (width, height, depth, color_type,
     compression, filter_method, interlace) = struct.unpack(">IIBBBBB", ihdr)
    if width <= 0 or height <= 0:
        raise PngError("非法尺寸：%dx%d" % (width, height))
    if depth != 8:
        raise PngError("不支持的位深：%d（仅支持 8）" % depth)
    channels = _channels(color_type)
    if compression != 0:
        raise PngError("不支持的压缩方式：%d" % compression)
    if filter_method != 0:
        raise PngError("不支持的过滤方式：%d" % filter_method)
    if interlace != 0:
        raise PngError("不支持隔行扫描：%d" % interlace)
    idat_parts = []
    idat_chunks = 0
    seen_iend = False
    for kind, payload in chunks[1:]:
        if kind == b"IDAT":
            idat_parts.append(payload)
            idat_chunks += 1
        elif kind == b"IEND":
            seen_iend = True
            break
    if not seen_iend:
        raise PngError("缺少 IEND 分块")
    if not idat_parts:
        raise PngError("缺少 IDAT 分块")
    try:
        raw = zlib.decompress(b"".join(idat_parts))
    except zlib.error as error:
        raise PngError("IDAT 解压失败：%s" % error)
    stride = width * channels
    expected = height * (stride + 1)
    if len(raw) != expected:
        raise PngError("像素数据长度不符：期望 %d 字节，实际 %d" % (expected, len(raw)))
    out = bytearray()
    previous = None
    at = 0
    for _ in range(height):
        filter_type = raw[at]
        at += 1
        if filter_type > 4:
            raise PngError("不支持的 filter：%d" % filter_type)
        line = raw[at:at + stride]
        at += stride
        row = _unfilter_row(filter_type, line, previous, channels)
        out.extend(row)
        previous = row
    if len(out) != width * height * channels:
        raise PngError("像素数量与尺寸不匹配")
    return {
        "width": width,
        "height": height,
        "color_type": color_type,
        "pixels": bytes(out),
        "idat_chunks": idat_chunks,
    }
