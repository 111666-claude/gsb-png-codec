"""命令行入口：生成 PNG、看信息、打印像素。"""

import argparse
import struct
import sys
import zlib

from .png import CHANNELS, SIGNATURE, PngError, decode, encode, split_chunks


def _paeth(a, b, c):
    estimate = a + b - c
    pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _filter_row(filter_type, line, previous, bpp):
    out = bytearray()
    for index, value in enumerate(line):
        left = line[index - bpp] if index >= bpp else 0
        up = previous[index] if previous is not None else 0
        up_left = previous[index - bpp] if previous is not None and index >= bpp else 0
        if filter_type == 0:
            predictor = 0
        elif filter_type == 1:
            predictor = left
        elif filter_type == 2:
            predictor = up
        elif filter_type == 3:
            predictor = (left + up) // 2
        else:
            predictor = _paeth(left, up, up_left)
        out.append((value - predictor) & 0xFF)
    return bytes(out)


def _reference_chunk(kind, payload):
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", crc)


def reference_png(width, height, rows, filters, split=1):
    """参考实现：按 PNG 规范用给定的 filter 与分块方式打包（样本用）。"""
    raw = bytearray()
    previous = None
    for row, filter_type in zip(rows, filters):
        line = bytes(row)
        raw.append(filter_type)
        raw.extend(_filter_row(filter_type, line, previous, 3))
        previous = line
    payload = zlib.compress(bytes(raw))
    size = max(1, (len(payload) + split - 1) // split)
    chunks = [payload[at:at + size] for at in range(0, len(payload), size)]
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    out = SIGNATURE + _reference_chunk(b"IHDR", header)
    for chunk in chunks:
        out += _reference_chunk(b"IDAT", chunk)
    return out + _reference_chunk(b"IEND", b"")


def gradient(width, height):
    """生成一张按坐标渐变的 RGB 图。"""
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            pixels.extend(((x * 37) % 256, (y * 53) % 256, ((x + y) * 29) % 256))
    return bytes(pixels)


def rows_of(width, height):
    """把渐变图切成一行一行。"""
    full = gradient(width, height)
    stride = width * 3
    return [full[at:at + stride] for at in range(0, len(full), stride)]


def sample(name):
    """构造样本（按规范打包，解码器必须能读回）。"""
    if name == "paeth":
        return reference_png(4, 4, rows_of(4, 4), [4] * 4)
    if name == "mixed":
        return reference_png(4, 4, rows_of(4, 4), [0, 1, 2, 3])
    if name == "split":
        return reference_png(6, 6, rows_of(6, 6), [0] * 6, split=4)
    raise PngError("不认识的样本：%s" % name)


def check_crc(data):
    """独立校验每个分块的 CRC（不依赖 pngcodec 的编解码）。"""
    if not data.startswith(SIGNATURE):
        return "bad"
    offset = len(SIGNATURE)
    ok = True
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        stored = struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != stored:
            ok = False
        offset += 12 + length
    return "ok" if ok else "bad"


def file_info(data):
    width = height = depth = color_type = 0
    idat_chunks = 0
    for kind, payload in split_chunks(data, verify_crc=False):
        if kind == b"IHDR":
            width, height, depth, color_type = struct.unpack(">IIBB", payload[:10])
        elif kind == b"IDAT":
            idat_chunks += 1
    return "width=%d height=%d bit_depth=%d color_type=%d idat_chunks=%d crc=%s" % (
        width, height, depth, color_type, idat_chunks, check_crc(data))


def build_parser():
    parser = argparse.ArgumentParser(prog="png-codec", description="PNG 读写")
    parser.add_argument("--make", help="生成 WxH 的测试图，例如 2x2")
    parser.add_argument("--sample", help="paeth / mixed / split")
    parser.add_argument("--out", help="写出的文件")
    parser.add_argument("--info", help="查看文件信息")
    parser.add_argument("--pixels", help="打印解码后的像素")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.make:
            width, _, height = args.make.partition("x")
            data = encode(int(width), int(height), gradient(int(width), int(height)))
            with open(args.out, "wb") as handle:
                handle.write(data)
            print("wrote=%s bytes=%d" % (args.out, len(data)))
        elif args.sample:
            data = sample(args.sample)
            with open(args.out, "wb") as handle:
                handle.write(data)
            print("wrote=%s bytes=%d" % (args.out, len(data)))
        elif args.info:
            with open(args.info, "rb") as handle:
                print(file_info(handle.read()))
        elif args.pixels:
            with open(args.pixels, "rb") as handle:
                result = decode(handle.read())
            stride = result["width"] * CHANNELS[result["color_type"]]
            for row in range(result["height"]):
                line = result["pixels"][row * stride:(row + 1) * stride]
                print("row=%d hex=%s" % (row, line.hex()))
        else:
            print("错误：需要 --make/--sample/--info/--pixels", file=sys.stderr)
            return 2
    except (PngError, OSError, ValueError, zlib.error) as error:
        print("错误：%s" % error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
