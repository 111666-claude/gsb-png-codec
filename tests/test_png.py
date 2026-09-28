import struct
import unittest
import zlib

from pngcodec.png import (
    IDAT_LIMIT,
    SIGNATURE,
    PngError,
    _chunk,
    decode,
    encode,
    split_chunks,
)
from pngcodec.cli import (
    _reference_chunk,
    check_crc,
    gradient,
    reference_png,
    rows_of,
    sample,
)


class EncodeTest(unittest.TestCase):
    def test_round_trip_rgb(self):
        pixels = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 9, 9, 9])
        data = encode(2, 2, pixels)
        result = decode(data)
        self.assertEqual((result["width"], result["height"]), (2, 2))
        self.assertEqual(result["pixels"], pixels)

    def test_round_trip_rgba(self):
        pixels = bytes([1, 2, 3, 4, 5, 6, 7, 8])
        result = decode(encode(2, 1, pixels, color_type=6))
        self.assertEqual(result["color_type"], 6)
        self.assertEqual(result["pixels"], pixels)

    def test_size_mismatch(self):
        with self.assertRaises(PngError):
            encode(2, 2, b"\x00" * 5)

    def test_unknown_color_type(self):
        with self.assertRaises(PngError):
            encode(1, 1, b"\x00", color_type=7)


class DecodeTest(unittest.TestCase):
    def test_rejects_other_format(self):
        with self.assertRaises(PngError):
            decode(b"GIF89a")

    def test_encoded_stream_starts_with_signature(self):
        self.assertTrue(encode(1, 1, b"\x01\x02\x03").startswith(b"\x89PNG\r\n\x1a\n"))

    def test_compressed_payload_is_smaller(self):
        pixels = bytes([7, 7, 7] * 64)
        self.assertLess(len(encode(8, 8, pixels)), len(pixels))


def _pseudo_random(length, seed=12345):
    out = bytearray()
    state = seed
    while len(out) < length:
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((state >> 8) & 0xFF)
    return bytes(out[:length])


def _idat_payloads(data):
    return [payload for kind, payload in split_chunks(data) if kind == b"IDAT"]


class CrcTest(unittest.TestCase):
    def test_own_output_crc_ok(self):
        self.assertEqual(check_crc(encode(3, 2, gradient(3, 2))), "ok")

    def test_chunk_matches_reference(self):
        payload = b"hello png"
        self.assertEqual(_chunk(b"IDAT", payload), _reference_chunk(b"IDAT", payload))

    def test_bad_crc_reports_offset(self):
        data = bytearray(encode(2, 2, gradient(2, 2)))
        offset = len(data) - 12  # IEND 分块的起始偏移
        data[-1] ^= 0xFF  # 弄坏 IEND 的 CRC
        with self.assertRaises(PngError) as caught:
            decode(bytes(data))
        self.assertIn(str(offset), str(caught.exception))
        self.assertEqual(check_crc(bytes(data)), "bad")


class FilterTest(unittest.TestCase):
    def _filter_bytes(self, data, height, stride):
        raw = zlib.decompress(b"".join(_idat_payloads(data)))
        return [raw[row * (stride + 1)] for row in range(height)]

    def test_adaptive_filter_picks_best(self):
        # 纯色图：首行 Sub(1) 最优，后续行 Up(2) 得 0 分
        pixels = bytes([200, 100, 50] * 4 * 3)
        filters = self._filter_bytes(encode(4, 3, pixels), 3, 12)
        self.assertEqual(filters, [1, 2, 2])

    def test_all_five_filters_round_trip(self):
        rows = rows_of(5, 5)
        data = reference_png(5, 5, rows, [0, 1, 2, 3, 4])
        self.assertEqual(decode(data)["pixels"], gradient(5, 5))

    def test_unknown_filter_rejected(self):
        raw = bytes([5]) + bytes(6)
        data = (SIGNATURE
                + _reference_chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 1, 8, 2, 0, 0, 0))
                + _reference_chunk(b"IDAT", zlib.compress(raw))
                + _reference_chunk(b"IEND", b""))
        with self.assertRaises(PngError):
            decode(data)


class IdatSplitTest(unittest.TestCase):
    def test_large_image_splits_idat(self):
        width, height = 64, 64
        pixels = _pseudo_random(width * height * 3)
        data = encode(width, height, pixels)
        payloads = _idat_payloads(data)
        self.assertGreater(len(payloads), 1)
        for payload in payloads:
            self.assertLessEqual(len(payload), IDAT_LIMIT)
        self.assertEqual(decode(data)["pixels"], pixels)

    def test_split_sample_decodes(self):
        result = decode(sample("split"))
        self.assertEqual(result["idat_chunks"], 4)
        self.assertEqual(result["pixels"], gradient(6, 6))


class StructureTest(unittest.TestCase):
    def test_missing_iend(self):
        data = encode(2, 2, gradient(2, 2))[:-12]
        with self.assertRaises(PngError):
            decode(data)

    def test_ihdr_must_be_first(self):
        data = (SIGNATURE
                + _reference_chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03"))
                + _reference_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + _reference_chunk(b"IEND", b""))
        with self.assertRaises(PngError):
            decode(data)

    def test_chunk_length_beyond_file(self):
        data = encode(2, 2, gradient(2, 2))[:-5]
        with self.assertRaises(PngError):
            decode(data)

    def test_truncated_payload(self):
        data = SIGNATURE + struct.pack(">I", 100) + b"IHDR" + b"\x00" * 4
        with self.assertRaises(PngError) as caught:
            decode(data)
        self.assertIn(str(len(SIGNATURE)), str(caught.exception))

    def _with_ihdr(self, **fields):
        values = dict(width=1, height=1, depth=8, color_type=2,
                      compression=0, filter_method=0, interlace=0)
        values.update(fields)
        ihdr = struct.pack(">IIBBBBB", values["width"], values["height"],
                           values["depth"], values["color_type"],
                           values["compression"], values["filter_method"],
                           values["interlace"])
        raw = bytes([0]) + bytes(3)
        return (SIGNATURE + _reference_chunk(b"IHDR", ihdr)
                + _reference_chunk(b"IDAT", zlib.compress(raw))
                + _reference_chunk(b"IEND", b""))

    def test_rejects_bit_depth_16(self):
        with self.assertRaises(PngError):
            decode(self._with_ihdr(depth=16))

    def test_rejects_color_type_3(self):
        with self.assertRaises(PngError):
            decode(self._with_ihdr(color_type=3))

    def test_rejects_interlace(self):
        with self.assertRaises(PngError):
            decode(self._with_ihdr(interlace=1))

    def test_pixel_count_mismatch(self):
        ihdr = struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)
        raw = bytes([0]) + bytes(6)  # 只有一行
        data = (SIGNATURE + _reference_chunk(b"IHDR", ihdr)
                + _reference_chunk(b"IDAT", zlib.compress(raw))
                + _reference_chunk(b"IEND", b""))
        with self.assertRaises(PngError):
            decode(data)


class InvariantTest(unittest.TestCase):
    def test_deterministic_encoding(self):
        pixels = gradient(7, 5)
        self.assertEqual(encode(7, 5, pixels), encode(7, 5, pixels))

    def test_round_trip_samples(self):
        for name, width, height in (("paeth", 4, 4), ("mixed", 4, 4), ("split", 6, 6)):
            result = decode(sample(name))
            self.assertEqual(result["pixels"], gradient(width, height))

    def test_reference_pixels_match_own_decoder(self):
        for name in ("mixed", "split"):
            reference = sample(name)
            result = decode(reference)
            again = decode(encode(result["width"], result["height"], result["pixels"]))
            self.assertEqual(again["pixels"], result["pixels"])
            self.assertEqual(check_crc(reference), "ok")


if __name__ == "__main__":
    unittest.main()
