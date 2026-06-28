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
from PIL import Image

CEL_BYTES = 3072
CEL_W = CEL_H = 64
PAL_BYTES = 128
PAL_COLORS = 64
T1_ENTRY = 14

ANIM_TYPES = [
    "eye_right",
    "eye_left",
    "l2_right",
    "l2_left",
    "l3_right",
    "l3_left",
    "l4_right",
    "l4_left"
]


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
                A = 0
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
            frame_cache[t3w] = [(vals[j * 2], vals[j * 2 + 1]) for j in range(4)]

    for a in anims:
        a["frames"] = [frame_cache[o] for o in a["t3_offs"]]

    return anims


def render_frame(cel_info, palette, cel_data):
    canvas = np.zeros((128, 128, 4), dtype=np.uint8)
    pal_np = np.array(palette, dtype=np.uint8)

    for i, (ci, flags) in enumerate(cel_info):
        col = i % 2
        bit4_set = bool(flags & 0x0004)

        px, py = col * 64, (i // 2) * 64
        cel_indexes = parse_cel(cel_data, ci)
        tile_rgba = pal_np[cel_indexes].reshape(CEL_H, CEL_W, 4)

        if bit4_set:
            tile_rgba = np.fliplr(tile_rgba)

        canvas[py:py + 64, px:px + 64] = tile_rgba

    im = Image.fromarray(canvas, "RGBA")

    return im


def main():
    parser = argparse.ArgumentParser(description="Furby Connect eye renderer")
    png_group = parser.add_mutually_exclusive_group()
    png_group.add_argument("--frames", dest="frames", action="store_true", help="Render PNGs")
    png_group.add_argument("--no-frames", dest="frames", action="store_false", help="Do not render PNGs")
    gif_group = parser.add_mutually_exclusive_group()
    gif_group.add_argument("--videos", dest="videos", action="store_true", help="Render GIFs")
    gif_group.add_argument("--no-videos", dest="videos", action="store_false", help="Do not render GIFs")
    fulls_group = parser.add_mutually_exclusive_group()
    fulls_group.add_argument("--fulls", dest="fulls", action="store_true", help="Render composite 300x128 full GIFs")
    fulls_group.add_argument("--no-fulls", dest="fulls", action="store_false", help="Do not render composite full GIFs")

    parser.set_defaults(frames=False, videos=True, fulls=True)
    parser.add_argument("--anim-dump-count", type=int, default=None, metavar="N",
                        help="Only dump first N animations")
    parser.add_argument("folders", nargs="+", help="Folder containing .SPR .CEL .PAL files")
    args = parser.parse_args()

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

        t0 = time.perf_counter()
        spr_path = find_file(".SPR")
        cel_path = find_file(".CEL")
        pal_path = find_file(".PAL")
        name = os.path.splitext(os.path.basename(spr_path))[0]

        with open(spr_path, "rb") as f:
            spr_data = f.read()
        with open(cel_path, "rb") as f:
            cel_data = f.read()
        with open(pal_path, "rb") as f:
            pal_data = f.read()
        t_io += (time.perf_counter() - t0)

        t0 = time.perf_counter()
        palettes = parse_pal(pal_data)
        animations = parse_spr(spr_data)
        t_parsing += (time.perf_counter() - t0)

        num_pals = len(palettes)
        num_cels = len(cel_data) // CEL_BYTES
        num_anims = len(animations)
        dump_anims = args.anim_dump_count or num_anims

        print(f"{name}: {num_cels} cels  {num_pals} palettes  {num_anims} anims  (dumping {dump_anims})")

        t0 = time.perf_counter()
        out_dir = os.path.join("out", folder)
        if args.frames:
            os.makedirs(os.path.join(out_dir, "frames"), exist_ok=True)
        if args.videos:
            os.makedirs(os.path.join(out_dir, "videos"), exist_ok=True)
        if args.fulls:
            os.makedirs(os.path.join(out_dir, "fulls"), exist_ok=True)
        t_io += (time.perf_counter() - t0)

        total = 0
        num_groups = (dump_anims + 7) // 8

        for gi in tqdm(range(num_groups), desc=f"Processing {name}"):
            if gi == 0:
                group_name = "manifest_anim"
            else:
                group_name = f"full_anim_{gi:04d}"

            start_ai = gi * 8
            end_ai = min(start_ai + 8, dump_anims)
            group_anims = animations[start_ai:end_ai]
            if not group_anims:
                continue

            max_frames = max(len(anim["frames"]) for anim in group_anims)

            full_face_frames = [Image.new("RGBA", (300, 128), (0, 0, 0, 0)) for _ in range(max_frames)]

            if args.frames:
                frames_dir = os.path.join(out_dir, "frames", group_name)
                os.makedirs(frames_dir, exist_ok=True)

            if args.videos:
                videos_dir = os.path.join(out_dir, "videos", group_name)
                os.makedirs(videos_dir, exist_ok=True)

            for internal_idx, anim in enumerate(group_anims):
                ai = start_ai + internal_idx
                type_name = ANIM_TYPES[ai % 8]
                pal = palettes[min(anim["pal_idx"], num_pals - 1)]

                is_right = "right" in type_name
                x_offset = 172 if is_right else 0

                frames_for_gif = []
                for fi, cels in enumerate(anim["frames"]):
                    t0 = time.perf_counter()
                    img = render_frame(cels, pal, cel_data)
                    t_rendering += (time.perf_counter() - t0)

                    if args.fulls and fi < len(full_face_frames):
                        t0 = time.perf_counter()
                        temp_canvas = Image.new("RGBA", (300, 128), (0, 0, 0, 0))
                        temp_canvas.paste(img, (x_offset, 0))
                        full_face_frames[fi] = Image.alpha_composite(full_face_frames[fi], temp_canvas)
                        t_rendering += (time.perf_counter() - t0)

                    if args.frames:
                        t0 = time.perf_counter()
                        if gi == 0:
                            frame_filename = f"{ai}_frame_{fi:04d}.bmp"
                        else:
                            frame_filename = f"{type_name}_{ai:04d}_frame_{fi:04d}.bmp"
                        img.convert("RGB").save(os.path.join(frames_dir, frame_filename))
                        t_saving += (time.perf_counter() - t0)

                    frames_for_gif.append(img)
                    total += 1

                if frames_for_gif and args.videos:
                    t0 = time.perf_counter()
                    if gi == 0:
                        gif_filename = f"{ai}.gif"
                    else:
                        gif_filename = f"{type_name}_{ai:04d}.gif"

                    gif_path = os.path.join(videos_dir, gif_filename)
                    frames_for_gif[0].save(
                        gif_path,
                        save_all=True,
                        append_images=frames_for_gif[1:],
                        duration=66,
                        loop=0,
                        disposal=2
                    )
                    t_saving += (time.perf_counter() - t0)

            if args.fulls and full_face_frames:
                t0 = time.perf_counter()
                gif_filename = f"{group_name}.gif"
                gif_path = os.path.join(out_dir, "fulls", gif_filename)

                full_face_frames[0].save(
                    gif_path,
                    save_all=True,
                    append_images=full_face_frames[1:],
                    duration=66,
                    loop=0,
                    disposal=2
                )
                t_saving += (time.perf_counter() - t0)

        print(f"\nDone - {total} frames processed → {out_dir}/")

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
