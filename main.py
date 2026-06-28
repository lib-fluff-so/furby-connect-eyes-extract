#!/usr/bin/env python3
"""
Furby Connect SPR/CEL/PAL renderer
"""

import struct
import os
import argparse
import time
import numpy as np
from tqdm import tqdm
from PIL import Image, ImageDraw

CEL_BYTES = 3072
CEL_W = CEL_H = 64
PAL_BYTES = 128
PAL_COLORS = 64
T1_ENTRY = 14


def parse_pal(data):
    palettes = []
    for pi in range(len(data) // PAL_BYTES):
        pal, off = [], pi * PAL_BYTES
        for ci in range(PAL_COLORS):
            val = struct.unpack_from("<H", data, off + ci * 2)[0]
            A = 0xff if (val & 0x8000) == 0 else 0
            R = (val & 0x7C00) >> 7
            G = (val & 0x03E0) >> 2
            B = (val & 0x001F) << 3
            if ci == 0:
                A = 0  # index 0 = chroma key
            pal.append((R, G, B, A))
        palettes.append(pal)
    return palettes


def parse_cel(data, idx):
    off = idx * CEL_BYTES
    chunk = np.frombuffer(data, dtype=np.uint8, count=CEL_BYTES, offset=off)
    chunks = chunk.reshape(-1, 3)
    b0, b1, b2 = chunks[:, 0], chunks[:, 1], chunks[:, 2]
    pixels = np.empty((chunks.shape[0], 4), dtype=np.uint8)
    pixels[:, 0] = b0 >> 2
    pixels[:, 1] = ((b0 & 0x03) << 4) | (b1 >> 4)
    pixels[:, 2] = ((b1 & 0x0F) << 2) | (b2 >> 6)
    pixels[:, 3] = b2 & 0x3F
    return pixels.flatten()


def detect_t1_count(data):
    def u16(o):
        return struct.unpack_from("<H", data, o)[0]

    def u32(o):
        return struct.unpack_from("<I", data, o)[0]

    count = 0
    while True:
        off = count * T1_ENTRY
        if off + T1_ENTRY > len(data): break
        fc = u16(off)
        t2_boff = u32(off + 2) * 2
        term = u32(off + 10)
        if t2_boff <= (count + 1) * T1_ENTRY: break
        if (term & 0xFFFF) != 0x0040: break
        if fc > 50000: break
        count += 1
    return count


def parse_spr(data):
    def u16(o):
        return struct.unpack_from("<H", data, o)[0]

    def u32(o):
        return struct.unpack_from("<I", data, o)[0]

    t1_count = detect_t1_count(data)
    print(f"  Detected {t1_count} T1 entries")

    anims = []
    for i in range(t1_count):
        off = i * T1_ENTRY
        fc = u16(off)
        t2_boff = u32(off + 2) * 2
        layer = u32(off + 6)
        pal_idx = (layer & 0xFFFF) // 64
        t3_offs = [u32(t2_boff + j * 4) for j in range(fc)]
        anims.append({"pal_idx": pal_idx, "layer": layer, "t3_offs": t3_offs})

    frame_cache = {}
    for a in anims:
        for t3w in a["t3_offs"]:
            if t3w in frame_cache: continue
            bo = t3w * 2
            vals = [u16(bo + j * 2) for j in range(9)]
            assert vals[-1] == 0xFFFF, f"Bad T3 terminator: {vals[-1]:#x}"
            frame_cache[t3w] = [vals[j * 2] for j in range(4)]

    for a in anims:
        a["frames"] = [frame_cache[o] for o in a["t3_offs"]]

    return anims


_CIRCLE_MASK = None


def get_circle_mask():
    global _CIRCLE_MASK
    if _CIRCLE_MASK is None:
        _CIRCLE_MASK = Image.new("L", (128, 128), 0)
        ImageDraw.Draw(_CIRCLE_MASK).ellipse((0, 0, 127, 127), fill=255)
    return _CIRCLE_MASK


def render_frame(cel_indices, palette, cel_data, circle_mask=False):
    canvas = np.zeros((128, 128, 4), dtype=np.uint8)
    pal_np = np.array(palette, dtype=np.uint8)

    for i, ci in enumerate(cel_indices):
        px, py = (i % 2) * 64, (i // 2) * 64
        cel_indexes = parse_cel(cel_data, ci)
        tile_rgba = pal_np[cel_indexes].reshape(CEL_H, CEL_W, 4)
        canvas[py:py + 64, px:px + 64] = tile_rgba

    im = Image.fromarray(canvas, "RGBA")

    if circle_mask:
        result = Image.new("RGBA", (128, 128), (0, 0, 0, 0))
        result.paste(im, mask=get_circle_mask())
        return result
    return im


def main():
    parser = argparse.ArgumentParser(description="Furby Connect eye renderer")
    mask_group = parser.add_mutually_exclusive_group()
    mask_group.add_argument("--circle-mask", dest="circle_mask", action="store_true", help="Apply circular mask")
    mask_group.add_argument("--no-circle-mask", dest="circle_mask", action="store_false",
                            help="Do not apply circular mask")
    png_group = parser.add_mutually_exclusive_group()
    png_group.add_argument("--frames", dest="frames", action="store_true", help="Render PNGs")
    png_group.add_argument("--no-frames", dest="frames", action="store_false", help="Do not render PNGs")
    gif_group = parser.add_mutually_exclusive_group()
    gif_group.add_argument("--videos", dest="videos", action="store_true", help="Render GIFs")
    gif_group.add_argument("--no-videos", dest="videos", action="store_false", help="Do not render GIFs")
    parser.set_defaults(circle_mask=False, frames=False, videos=True)
    parser.add_argument("--anim-dump-count", type=int, default=None, metavar="N",
                        help="Only dump first N animations")
    parser.add_argument("folders", nargs="+", help="Folder containing .SPR .CEL .PAL files")
    args = parser.parse_args()

    # Initialize time counters
    t_io = 0.0
    t_parsing = 0.0
    t_rendering = 0.0
    t_saving = 0.0

    t_start = time.perf_counter()

    for folder in args.folders:
        def find_file(ext):
            for file in os.listdir(folder):
                if file.upper().endswith(ext.upper()):
                    return os.path.join(folder, file)
            raise FileNotFoundError(f"No {ext} file in {folder}")

        # IO Stage 1: File discovery
        t0 = time.perf_counter()
        spr_path = find_file(".SPR")
        cel_path = find_file(".CEL")
        pal_path = find_file(".PAL")
        name = os.path.splitext(os.path.basename(spr_path))[0]

        # IO Stage 2: Reading files
        with open(spr_path, "rb") as f:
            spr_data = f.read()
        with open(cel_path, "rb") as f:
            cel_data = f.read()
        with open(pal_path, "rb") as f:
            pal_data = f.read()
        t_io += (time.perf_counter() - t0)

        # Parsing Stage
        t0 = time.perf_counter()
        palettes = parse_pal(pal_data)
        animations = parse_spr(spr_data)
        t_parsing += (time.perf_counter() - t0)

        num_pals = len(palettes)
        num_cels = len(cel_data) // CEL_BYTES
        num_anims = len(animations)
        dump_anims = args.anim_dump_count or num_anims

        print(f"{name}: {num_cels} cels  {num_pals} palettes  {num_anims} anims  (dumping {dump_anims})")

        # IO Stage 3: Directory creation
        t0 = time.perf_counter()
        out_dir = os.path.join("out", folder)
        frames_dir = os.path.join(out_dir, "frames")
        videos_dir = os.path.join(out_dir, "videos")
        if args.frames: os.makedirs(frames_dir, exist_ok=True)
        if args.videos: os.makedirs(videos_dir, exist_ok=True)
        t_io += (time.perf_counter() - t0)

        total = 0
        for ai, anim in tqdm(enumerate(animations[:dump_anims]), total=dump_anims):
            pal = palettes[min(anim["pal_idx"], num_pals - 1)]

            frames_for_gif = []
            for fi, cels in enumerate(anim["frames"]):
                # Rendering Stage
                t0 = time.perf_counter()
                img = render_frame(cels, pal, cel_data, circle_mask=args.circle_mask)
                t_rendering += (time.perf_counter() - t0)

                # Saving Stage (PNG)
                if args.frames:
                    t0 = time.perf_counter()
                    img.convert("RGB").save(os.path.join(frames_dir, f"anim_{ai:03d}_frame_{fi:04d}.bmp"))
                    t_saving += (time.perf_counter() - t0)

                frames_for_gif.append(img)
                total += 1

            # Saving Stage (GIF)
            if frames_for_gif and args.videos:
                t0 = time.perf_counter()
                gif_path = os.path.join(videos_dir, f"anim_{ai:04d}.gif")
                frames_for_gif[0].save(
                    gif_path,
                    save_all=True,
                    append_images=frames_for_gif[1:],
                    duration=66,
                    loop=0,
                    disposal=2
                )
                t_saving += (time.perf_counter() - t0)

        print(f"\nDone - {total} frames & {len(animations[:dump_anims])} GIFs → {out_dir}/")

    t_total = time.perf_counter() - t_start

    p_io = (t_io / t_total) * 100
    p_parsing = (t_parsing / t_total) * 100
    p_rendering = (t_rendering / t_total) * 100
    p_saving = (t_saving / t_total) * 100

    print(f"Total Time : {t_total:.4f}s")
    print(f"File IO    : {t_io:.4f}s ({p_io:.1f}%)")
    print(f"Parsing    : {t_parsing:.4f}s ({p_parsing:.1f}%)")
    print(f"Rendering  : {t_rendering:.4f}s ({p_rendering:.1f}%)")
    print(f"File Saving: {t_saving:.4f}s ({p_saving:.1f}%)")


if __name__ == "__main__":
    main()
