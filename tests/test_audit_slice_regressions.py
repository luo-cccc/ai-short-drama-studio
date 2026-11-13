"""Spatial grid semantics, safe slicing, and PNG fidelity regressions."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import zlib

from scripts.slice_grid import (
    PNG_SIGNATURE, RawImage, _png_chunk, main, read_png_stdlib, slice_image,
    write_png_stdlib,
)


def image(width=60, height=60, *, channels=3, bit_depth=8, metadata=None):
    rows = []
    for y in range(height):
        values = [(x + y) % 256 for x in range(width * channels)]
        rows.append(bytes(values) if bit_depth == 8 else b"".join(struct.pack(">H", value * 257) for value in values))
    return RawImage(width, height, channels, bit_depth, rows, metadata)


def png(*, width=12, height=12, raw=None, compressed=None, ihdr=None, metadata=()):
    if ihdr is None:
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    if raw is None:
        raw = b"".join(b"\0" + bytes([0, 1, 2]) * width for _ in range(height))
    if compressed is None:
        compressed = zlib.compress(raw)
    return (PNG_SIGNATURE + _png_chunk(b"IHDR", ihdr)
            + b"".join(_png_chunk(kind, payload) for kind, payload in metadata)
            + _png_chunk(b"IDAT", compressed) + _png_chunk(b"IEND", b""))


class SliceAuditRegressionTests(unittest.TestCase):
    def test_spatial_manifest_has_views_without_action_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "space.png"
            write_png_stdlib(image(), source)
            with redirect_stdout(io.StringIO()):
                result = main([str(source), "--output", str(root / "slices"),
                               "--grid-kind", "spatial", "--trim", "0"])
            self.assertEqual(0, result)
            manifest = json.loads((root / "slices/slice-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("spatial", manifest["grid_kind"])
            self.assertEqual(9, len(manifest["space_views"]))
            for key in ("first_frame", "last_frame", "middle_keyframes"):
                self.assertNotIn(key, manifest)

    def test_storyboard_remains_default_with_first_and_last_frames(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            manifest = slice_image(source, root / "slices", trim=0)
            self.assertEqual("Shot_01.png", manifest["first_frame"])
            self.assertEqual("Shot_09.png", manifest["last_frame"])
            self.assertNotIn("space_views", manifest)

    def test_source_in_output_directory_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "Shot_01.png"
            write_png_stdlib(image(), source)
            original = source.read_bytes()
            with self.assertRaisesRegex(ValueError, "源图"):
                slice_image(source, root, trim=0)
            self.assertEqual(original, source.read_bytes())
            self.assertEqual({source.name}, {path.name for path in root.iterdir()})

    def test_existing_last_slice_blocks_every_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            output = root / "slices"
            output.mkdir()
            existing = output / "Shot_09.png"
            existing.write_bytes(b"user image")
            with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                slice_image(source, output)
            self.assertEqual(b"user image", existing.read_bytes())
            self.assertEqual({existing.name}, {path.name for path in output.iterdir()})

    def test_existing_manifest_blocks_every_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            output = root / "slices"
            output.mkdir()
            manifest = output / "slice-manifest.json"
            manifest.write_bytes(b"existing manifest")
            with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                slice_image(source, output)
            self.assertEqual(b"existing manifest", manifest.read_bytes())
            self.assertEqual({manifest.name}, {path.name for path in output.iterdir()})

    def test_prefix_cannot_escape_output_or_use_windows_path_syntax(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            for prefix in ("../outside", "..\\outside", "/absolute", "C:\\outside", "name:stream", "bad/child", "bad\\child"):
                with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "prefix"):
                    slice_image(source, root / "slices", prefix=prefix)
            self.assertEqual({source.name}, {path.name for path in root.iterdir()})

    def test_write_failure_removes_only_files_created_by_this_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            output = root / "slices"
            output.mkdir()
            unrelated = output / "notes.txt"
            unrelated.write_bytes(b"keep")
            original_open = Path.open

            def failing_open(path, mode="r", *args, **kwargs):
                if mode == "xb" and path.name == "Shot_03.png":
                    raise OSError("simulated write failure")
                return original_open(path, mode, *args, **kwargs)

            with patch.object(Path, "open", failing_open), self.assertRaisesRegex(OSError, "simulated"):
                slice_image(source, output)
            self.assertEqual({unrelated.name}, {path.name for path in output.iterdir()})
            self.assertEqual(b"keep", unrelated.read_bytes())

    def test_encoding_failure_does_not_create_any_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "board.png"
            write_png_stdlib(image(), source)
            with patch("scripts.slice_grid._png_payload", side_effect=ValueError("encode failed")):
                with self.assertRaisesRegex(ValueError, "encode failed"):
                    slice_image(source, root / "slices")
            self.assertFalse((root / "slices").exists())

    def test_png_crop_preserves_transparency_and_color_chunks(self):
        metadata = [
            (b"gAMA", struct.pack(">I", 45455)),
            (b"cHRM", struct.pack(">8I", 31270, 32900, 64000, 33000, 30000, 60000, 15000, 6000)),
            (b"iCCP", b"test-profile\0\0" + zlib.compress(b"profile payload")),
            (b"sBIT", b"\x08\x08\x08"),
            (b"pHYs", struct.pack(">IIB", 3780, 3780, 1)),
            (b"tRNS", struct.pack(">HHH", 1, 2, 3)),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.png"
            source.write_bytes(png(metadata=metadata))
            decoded = read_png_stdlib(source)
            cropped = decoded.crop(0, 0, 4, 4)
            target = root / "crop.png"
            write_png_stdlib(cropped, target)
            actual = target.read_bytes()
            for kind, payload in metadata:
                self.assertIn(_png_chunk(kind, payload), actual)
            self.assertEqual(metadata, read_png_stdlib(target).metadata)
            self.assertEqual([bytes([0, 1, 2]) * 4] * 4, read_png_stdlib(target).rows)
            srgb = root / "srgb.png"
            srgb.write_bytes(png(metadata=[(b"sRGB", b"\0")]))
            self.assertEqual([(b"sRGB", b"\0")], read_png_stdlib(srgb).crop(0, 0, 4, 4).metadata)

    def test_supported_depths_and_channels_keep_pixel_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for bit_depth in (8, 16):
                for channels in (1, 2, 3, 4):
                    with self.subTest(bit_depth=bit_depth, channels=channels):
                        original = image(12, 12, channels=channels, bit_depth=bit_depth)
                        path = root / f"pixels-{channels}-{bit_depth}.png"
                        write_png_stdlib(original, path)
                        decoded = read_png_stdlib(path)
                        self.assertEqual(original.rows, decoded.rows)
                        cropped = decoded.crop(4, 4, 8, 8)
                        stride = channels * (bit_depth // 8)
                        self.assertEqual([row[4 * stride:8 * stride] for row in original.rows[4:8]], cropped.rows)

    def test_malformed_png_returns_cli_diagnostic_without_output(self):
        raw = b"".join(b"\0" + bytes([0, 1, 2]) * 12 for _ in range(12))
        base = png(raw=raw)
        bad_crc = bytearray(base)
        bad_crc[29] ^= 1
        cases = {
            "truncated-block": base[:-2],
            "missing-IEND": base[:-12],
            "CRC": bytes(bad_crc),
            "IHDR-size": png(ihdr=b"short"),
            "bad-compression": png(compressed=b"not compressed data"),
            "incomplete-compression": png(compressed=zlib.compress(raw)[:-2]),
            "extra-compression": png(compressed=zlib.compress(raw) + zlib.compress(b"extra")),
            "short-pixels": png(raw=raw[:-1]),
            "extra-pixels": png(raw=raw + b"extra"),
            "filter": png(raw=b"\x05" + raw[1:]),
            "zero-size": png(width=0),
            "trailing-data": base + b"extra",
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, payload in cases.items():
                with self.subTest(name=name):
                    source = root / f"{name}.png"
                    source.write_bytes(payload)
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        result = main([str(source), "--output", str(root / name)])
                    self.assertEqual(1, result, stdout.getvalue())
                    self.assertIn("ERROR:", stderr.getvalue())
                    self.assertNotIn("Traceback", stderr.getvalue())
                    self.assertFalse((root / name).exists())

    def test_crop_rejects_empty_outside_and_inconsistent_images(self):
        sample = image(12, 12)
        for box in ((12, 0, 13, 4), (0, 0, 0, 4), (-1, 0, 4, 4), (0, 0, 4, 13)):
            with self.subTest(box=box), self.assertRaises(ValueError):
                sample.crop(*box)
        with self.assertRaises(ValueError):
            RawImage(12, 12, 3, 8, [b"short"] * 12)

    def test_t1_rejects_spatial_grid_kind_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "character.png"
            write_png_stdlib(image(), source)
            with self.assertRaisesRegex(ValueError, "仅用于 grid"):
                slice_image(source, root / "slices", mode="t1", grid_kind="spatial")
            self.assertFalse((root / "slices").exists())


if __name__ == "__main__":
    unittest.main()
