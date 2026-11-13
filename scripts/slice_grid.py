#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""将 T5 空间九视角、T6/T6B 九宫格故事板或 T1 角色设定图切分为单图。

标准库保留所支持 PNG 的像素、透明及常见色彩元数据；Pillow 可扩展图像格式支持。
默认不覆盖已有切图或清单。T5 请使用 --grid-kind spatial，避免误标为动作首尾帧。

用法示例：
  python -B -X utf8 scripts/slice_grid.py storyboard.png --output output/slices/SHOT-001 --mode grid
  python -B -X utf8 scripts/slice_grid.py character_t1.png --output output/slices/CHAR-WANQING --mode t1
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import re
import struct
import sys
import zlib


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRESERVED_PNG_CHUNKS = {b"tRNS", b"gAMA", b"cHRM", b"iCCP", b"sRGB", b"sBIT", b"pHYs"}


class UnsupportedPNG(ValueError):
    """A structurally valid PNG whose encoding needs Pillow."""


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


class RawImage:
    """轻量纯标准库内存图像容器（按行存储字节序列，支持无损裁剪与 PNG 读写）。"""

    def __init__(self, width: int, height: int, channels: int, bit_depth: int,
                 rows: list[bytes | bytearray], metadata: list[tuple[bytes, bytes]] | None = None):
        if width < 1 or height < 1 or channels not in (1, 2, 3, 4) or bit_depth not in (8, 16):
            raise ValueError("RawImage 尺寸、通道数或位深非法")
        self.width = width
        self.height = height
        self.channels = channels
        self.bit_depth = bit_depth
        self.sample_bytes = channels * (bit_depth // 8)
        self.rows = [bytes(r) for r in rows]
        if len(self.rows) != height or any(len(row) != width * self.sample_bytes for row in self.rows):
            raise ValueError("RawImage 行数或像素数据长度与尺寸不符")
        self.metadata = [(kind, bytes(data)) for kind, data in (metadata or [])]

    def crop(self, left: int, top: int, right: int, bottom: int) -> "RawImage":
        if not (0 <= left < right <= self.width and 0 <= top < bottom <= self.height):
            raise ValueError("裁剪区间须非空且位于源图范围内")
        start_byte = left * self.sample_bytes
        end_byte = right * self.sample_bytes
        cropped_rows = [row[start_byte:end_byte] for row in self.rows[top:bottom]]
        return RawImage(right - left, bottom - top, self.channels, self.bit_depth, cropped_rows, self.metadata)


def read_png_stdlib(path: Path) -> RawImage:
    """使用纯 Python 标准库解码 PNG（支持 8/16 位灰度、RGB、RGBA 及全部五种滤波器）。"""
    data = path.read_bytes()
    if len(data) < 8 or data[:8] != PNG_SIGNATURE:
        raise ValueError(f"不是合法的 PNG 文件：{path}")
    pos = 8
    width = height = bit_depth = color_type = interlace = None
    idat_chunks: list[bytes] = []
    metadata = []
    saw_iend = False
    idat_ended = False
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError("PNG 块头或校验数据截断")
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]
        if not re.fullmatch(rb"[A-Za-z]{4}", chunk_type):
            raise ValueError("PNG 块类型非法")
        if pos + 12 + length > len(data):
            raise ValueError("PNG 块数据截断")
        chunk_data = data[pos + 8:pos + 8 + length]
        checksum = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF != checksum:
            raise ValueError(f"PNG {chunk_type.decode('ascii')} 块 CRC 校验失败")
        if width is None and chunk_type != b"IHDR":
            raise ValueError("PNG 首块必须为 IHDR")
        pos += 12 + length
        if chunk_type == b"IHDR":
            if width is not None or length != 13:
                raise ValueError("PNG IHDR 重复或长度错误")
            width, height, bit_depth, color_type, compression, filtering, interlace = struct.unpack(">IIBBBBB", chunk_data)
            if not width or not height or compression != 0 or filtering != 0 or interlace not in (0, 1):
                raise ValueError("PNG IHDR 尺寸或编码方法非法")
        elif chunk_type == b"IDAT":
            if idat_ended:
                raise ValueError("PNG IDAT 块必须连续")
            idat_chunks.append(chunk_data)
        elif chunk_type == b"IEND":
            if length or pos != len(data):
                raise ValueError("PNG IEND 长度错误或结尾含额外数据")
            saw_iend = True
            break
        else:
            if idat_chunks:
                idat_ended = True
            if chunk_type == b"acTL":
                raise ValueError("动画 PNG 请先提取所需静帧，再执行切图")
            if chunk_type in PRESERVED_PNG_CHUNKS:
                if idat_chunks or any(kind == chunk_type for kind, _ in metadata):
                    raise ValueError("PNG 透明/色彩元数据位置错误或重复")
                metadata.append((chunk_type, chunk_data))
            elif chunk_type != b"PLTE" and not (chunk_type[0] & 32):
                raise ValueError(f"PNG 含不支持的关键块：{chunk_type.decode('ascii')}")
    if width is None or height is None or not idat_chunks or not saw_iend:
        raise ValueError(f"PNG 缺少关键块：{path}")
    if interlace != 0:
        raise UnsupportedPNG("纯标准库模式不支持隔行扫描（Interlaced）PNG，请安装 Pillow 或使用标准 PNG")
    channel_map = {0: 1, 2: 3, 4: 2, 6: 4}
    if color_type not in channel_map or bit_depth not in (8, 16):
        raise UnsupportedPNG(f"纯标准库模式仅支持 8/16位 RGB/RGBA/灰度 PNG（当前 color_type={color_type}, bit_depth={bit_depth}）")
    lengths = {b"gAMA": 4, b"cHRM": 32, b"sRGB": 1, b"pHYs": 9,
               b"sBIT": {0: 1, 2: 3, 4: 2, 6: 4}[color_type]}
    for kind, payload in metadata:
        if kind in lengths and len(payload) != lengths[kind]:
            raise ValueError(f"PNG {kind.decode('ascii')} 长度错误")
        if kind == b"tRNS" and (color_type not in (0, 2) or len(payload) != (2 if color_type == 0 else 6)):
            raise ValueError("PNG tRNS 透明信息与颜色类型不符")
    channels = channel_map[color_type]
    bpp = channels * (bit_depth // 8)
    stride = width * bpp
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(b"".join(idat_chunks)) + decoder.flush()
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError("PNG 压缩流截断或含额外数据")
    except zlib.error as error:
        raise ValueError(f"PNG 压缩数据非法：{error}") from error
    expected_len = height * (1 + stride)
    if len(raw) != expected_len:
        raise ValueError("PNG 解压数据长度与图像尺寸不符")
    rows: list[bytearray] = []
    offset = 0
    prev = bytearray(stride)
    for _ in range(height):
        filter_type = raw[offset]
        scanline = bytearray(raw[offset + 1:offset + 1 + stride])
        offset += 1 + stride
        if filter_type == 1:  # Sub
            for i in range(bpp, stride):
                scanline[i] = (scanline[i] + scanline[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                scanline[i] = (scanline[i] + prev[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = scanline[i - bpp] if i >= bpp else 0
                scanline[i] = (scanline[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = scanline[i - bpp] if i >= bpp else 0
                up = prev[i]
                up_left = prev[i - bpp] if i >= bpp else 0
                scanline[i] = (scanline[i] + _paeth_predictor(left, up, up_left)) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"未知的 PNG 滤波类型：{filter_type}")
        rows.append(scanline)
        prev = scanline
    return RawImage(width, height, channels, bit_depth, rows, metadata)


def _png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(chunk_type)
    crc = zlib.crc32(data, crc) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)


def _png_payload(image: RawImage) -> bytes:
    color_map = {1: 0, 2: 4, 3: 2, 4: 6}
    color_type = color_map[image.channels]
    ihdr = struct.pack(">IIBBBBB", image.width, image.height, image.bit_depth, color_type, 0, 0, 0)
    raw_scanlines = b"".join(b"\x00" + row for row in image.rows)
    idat = zlib.compress(raw_scanlines, level=6)
    return (
        PNG_SIGNATURE
        + _png_chunk(b"IHDR", ihdr)
        + b"".join(_png_chunk(kind, data) for kind, data in image.metadata if kind in PRESERVED_PNG_CHUNKS)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def write_png_stdlib(image: RawImage, path: Path) -> None:
    """写出像素及所保留的 PNG 透明、色彩元数据。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_png_payload(image))


def _crop_box_with_trim(
    x0: int, y0: int, x1: int, y1: int, trim_ratio: float
) -> tuple[int, int, int, int]:
    if trim_ratio <= 0:
        return x0, y0, x1, y1
    w = x1 - x0
    h = y1 - y0
    dx = int(round(w * trim_ratio))
    dy = int(round(h * trim_ratio))
    if w - 2 * dx >= 4:
        x0 += dx
        x1 -= dx
    if h - 2 * dy >= 4:
        y0 += dy
        y1 -= dy
    return x0, y0, x1, y1


def compute_grid_boxes(
    width: int, height: int, rows: int = 3, cols: int = 3, trim: float = 0.015, prefix: str = "Shot"
) -> list[dict]:
    """计算等分网格（默认 3×3 九宫格）每格的裁剪坐标与输出文件名。"""
    if rows < 1 or cols < 1:
        raise ValueError("rows 与 cols 必须为正整数")
    if not prefix or re.search(r'[<>:"/\\|?*\x00-\x1f]', prefix) or prefix.endswith((" ", ".")):
        raise ValueError("prefix 须为文件名前缀，不能含路径分隔符或非法文件名字符")
    if not 0.0 <= trim < 0.25:
        raise ValueError("trim 内缩比例须在 [0.0, 0.25) 范围内")
    if width < cols * 4 or height < rows * 4:
        raise ValueError(f"图像尺寸（{width}x{height}）过小，无法切分为 {rows}x{cols} 网格")
    boxes = []
    index = 1
    for r in range(rows):
        y0 = int(round(r * height / rows))
        y1 = int(round((r + 1) * height / rows))
        for c in range(cols):
            x0 = int(round(c * width / cols))
            x1 = int(round((c + 1) * width / cols))
            cx0, cy0, cx1, cy1 = _crop_box_with_trim(x0, y0, x1, y1, trim)
            boxes.append({
                "index": index,
                "row": r + 1,
                "col": c + 1,
                "name": f"{prefix}_{index:02d}.png",
                "box": [cx0, cy0, cx1, cy1],
            })
            index += 1
    return boxes


def compute_t1_boxes(width: int, height: int, split_ratio: float = 0.55, trim: float = 0.015) -> list[dict]:
    """计算 T1 角色完整设定图（左 55% 全身三视图 + 右 45% 2×2 四格头像）的裁剪坐标。"""
    if not 0.3 <= split_ratio <= 0.7:
        raise ValueError("split_ratio 须在 [0.3, 0.7] 范围内")
    if not 0.0 <= trim < 0.25:
        raise ValueError("trim 内缩比例须在 [0.0, 0.25) 范围内")
    if width < 40 or height < 20:
        raise ValueError(f"图像尺寸（{width}x{height}）过小，无法按 T1 版式切分")
    split_x = int(round(width * split_ratio))
    boxes = []
    # 左区整体三视图
    lx0, ly0, lx1, ly1 = _crop_box_with_trim(0, 0, split_x, height, trim)
    boxes.append({"index": 0, "role": "full_body_sheet", "name": "char_full_3views.png", "box": [lx0, ly0, lx1, ly1]})
    # 左区正、侧、背单列全身图
    view_names = ("char_body_01_front.png", "char_body_02_side90.png", "char_body_03_back.png")
    for i, view_name in enumerate(view_names):
        vx0 = int(round(i * split_x / 3))
        vx1 = int(round((i + 1) * split_x / 3))
        cx0, cy0, cx1, cy1 = _crop_box_with_trim(vx0, 0, vx1, height, trim)
        boxes.append({"index": i + 1, "role": f"body_view_{i + 1}", "name": view_name, "box": [cx0, cy0, cx1, cy1]})
    # 右区 2×2 四格面部特写
    right_w = width - split_x
    head_names = (
        (0, 0, "char_head_01_front.png"),
        (0, 1, "char_head_02_angle45.png"),
        (1, 0, "char_head_03_profile90.png"),
        (1, 1, "char_head_04_expression.png"),
    )
    for idx, (r, c, head_name) in enumerate(head_names, 4):
        hx0 = split_x + int(round(c * right_w / 2))
        hx1 = split_x + int(round((c + 1) * right_w / 2))
        hy0 = int(round(r * height / 2))
        hy1 = int(round((r + 1) * height / 2))
        cx0, cy0, cx1, cy1 = _crop_box_with_trim(hx0, hy0, hx1, hy1, trim)
        boxes.append({"index": idx, "role": f"head_view_{idx - 3}", "name": head_name, "box": [cx0, cy0, cx1, cy1]})
    return boxes


def _load_image(source: Path):
    """先完整解码；只有明确不支持的 PNG 编码才回退 Pillow。"""
    if source.suffix.lower() == ".png":
        try:
            return read_png_stdlib(source), None
        except UnsupportedPNG:
            pass
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise ValueError(f"无法使用纯标准库读取 {source}，请转为标准 8/16-bit PNG 或安装 Pillow") from exc
    pil_img = Image.open(source)
    try:
        pil_img.load()
    except Exception:
        pil_img.close()
        raise
    return None, pil_img


def _output_targets(source: Path, output_dir: Path, boxes: list[dict]) -> list[Path]:
    """在写任何文件前核对全部输出，包含最终清单。"""
    root = output_dir.resolve()
    source_resolved = source.resolve()
    targets = [output_dir / item["name"] for item in boxes] + [output_dir / "slice-manifest.json"]
    identities = set()
    for target in targets:
        resolved = target.resolve()
        if resolved.parent != root:
            raise ValueError(f"切图目标不能越出输出目录：{target}")
        if resolved == source_resolved:
            raise ValueError(f"切图输出不能覆盖源图：{target}")
        if target.exists() or target.is_symlink():
            raise ValueError(f"目标已存在，拒绝覆盖；请使用新的输出目录：{target}")
        identity = str(resolved).casefold()
        if identity in identities:
            raise ValueError(f"切图输出文件名重复：{target}")
        identities.add(identity)
    return targets


def _crop_payloads(raw_img, pil_img, boxes: list[dict], output_dir: Path):
    """在写入前完成所有裁剪和编码，避免后一个图块失败留下半套文件。"""
    records, payloads = [], []

    records = []
    for item in boxes:
        x0, y0, x1, y1 = item["box"]
        target = output_dir / item["name"]
        if raw_img is not None:
            sub = raw_img.crop(x0, y0, x1, y1)
            payload = _png_payload(sub)
            w, h = sub.width, sub.height
        else:
            sub_pil = pil_img.crop((x0, y0, x1, y1))
            try:
                options = {key: pil_img.info[key] for key in ("icc_profile", "transparency", "dpi") if key in pil_img.info}
                with io.BytesIO() as buffer:
                    sub_pil.save(buffer, format="PNG", **options)
                    payload = buffer.getvalue()
                w, h = sub_pil.size
            finally:
                sub_pil.close()
        records.append({**item, "path": str(target), "width": w, "height": h})
        payloads.append(payload)
    return records, payloads


def _write_outputs(targets: list[Path], payloads: list[bytes]) -> None:
    created = []
    try:
        for target, payload in zip(targets, payloads):
            with target.open("xb") as handle:
                created.append(target)
                handle.write(payload)
    except (OSError, ValueError):
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise


def slice_image(
    source: str | Path,
    output_dir: str | Path,
    *,
    mode: str = "grid",
    rows: int = 3,
    cols: int = 3,
    trim: float = 0.015,
    prefix: str = "Shot",
    grid_kind: str = "storyboard",
) -> dict:
    """切分故事板九宫格或 T1 角色板，并在输出目录生成 slice-manifest.json。"""
    source_path = Path(source)
    if not source_path.is_file():
        raise ValueError(f"输入图像不存在：{source_path}")
    out_path = Path(output_dir)

    if grid_kind not in ("storyboard", "spatial"):
        raise ValueError(f"未知九宫格用途：{grid_kind}")
    if mode != "grid" and grid_kind != "storyboard":
        raise ValueError("grid_kind 仅用于 grid 模式")
    raw_img, pil_img = _load_image(source_path)
    try:
        width, height = (raw_img.width, raw_img.height) if raw_img is not None else pil_img.size
        if mode == "grid":
            boxes = compute_grid_boxes(width, height, rows=rows, cols=cols, trim=trim, prefix=prefix)
        elif mode == "t1":
            boxes = compute_t1_boxes(width, height, trim=trim)
        else:
            raise ValueError(f"未知切图模式：{mode}")
        targets = _output_targets(source_path, out_path, boxes)
        records, payloads = _crop_payloads(raw_img, pil_img, boxes, out_path)
    finally:
        if pil_img is not None:
            pil_img.close()
    manifest: dict = {
        "source": str(source_path),
        "source_size": [width, height],
        "mode": mode,
        "trim": trim,
        "slices": records,
    }
    if mode == "grid" and records:
        manifest["grid_kind"] = grid_kind
        if grid_kind == "spatial":
            manifest["space_views"] = [r["name"] for r in records]
        else:
            manifest["first_frame"] = records[0]["name"]
            manifest["last_frame"] = records[-1]["name"]
            manifest["middle_keyframes"] = [r["name"] for r in records[1:-1]]
    elif mode == "t1" and records:
        manifest["full_body_sheet"] = records[0]["name"]
        manifest["body_views"] = [r["name"] for r in records[1:4]]
        manifest["head_views"] = [r["name"] for r in records[4:]]

    payloads.append((json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    out_path.mkdir(parents=True, exist_ok=True)
    _write_outputs(targets, payloads)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="将 3×3 九宫格故事板或 T1 角色板切分为独立高清单帧图像")
    parser.add_argument("image", help="待切分的 PNG 图像路径")
    parser.add_argument("--output", "-o", required=True, help="切分后单图输出目录")
    parser.add_argument("--mode", choices=["grid", "t1"], default="grid", help="grid: 3×3九宫格(默认)；t1: 左55%%三视图+右45%%四格头像")
    parser.add_argument("--grid-kind", choices=["storyboard", "spatial"], default="storyboard",
                        help="grid 用途：storyboard标首尾帧(默认)，spatial仅标空间视角（T5）")
    parser.add_argument("--rows", type=int, default=3, help="grid 模式行数（默认 3）")
    parser.add_argument("--cols", type=int, default=3, help="grid 模式列数（默认 3）")
    parser.add_argument("--trim", type=float, default=0.015, help="每格边缘内缩去线比例（默认 0.015，即 1.5%%）")
    parser.add_argument("--prefix", default="Shot", help="grid 模式输出文件名前缀（默认 Shot）")
    args = parser.parse_args(argv)
    try:
        manifest = slice_image(
            args.image,
            args.output,
            mode=args.mode,
            rows=args.rows,
            cols=args.cols,
            trim=args.trim,
            prefix=args.prefix,
            grid_kind=args.grid_kind,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
