import unittest

from pngcodec.png import PngError, decode, encode


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


if __name__ == "__main__":
    unittest.main()
