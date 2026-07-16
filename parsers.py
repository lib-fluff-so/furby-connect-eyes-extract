import os
import numpy as np
import struct

from typing import List, Optional

from PIL import Image

from images import write_indexed_png

"""CONSTANTS, DO NOT CHANGE"""
# PAL
PAL_COLORS = 64
ALPHA_MASK = 0b1000_0000_0000_0000
RED_MASK =   0b0111_1100_0000_0000
GREEN_MASK = 0b0000_0011_1110_0000
BLUE_MASK =  0b0000_0000_0001_1111
# CEL
CEL_BYTES = 3072
CEL_H = CEL_W = 64
FLAG_H_FLIP = 0x0004
# SPR
T1_ENTRY = 14
# Fulls
FULL_WIDTH = 300
# Uhm
DO_NOT_GENERATE_ANIM_0_IF_CREATING_FULLS = True

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

    return np.array(anims).reshape(-1, 8)


def parse_pal(data):
    """Parses PAL file -- a list of ARGB1555 PAL_COLORS palettes"""
    palettes = []
    # iterate through all palettes
    for pi in range(len(data) // (PAL_COLORS * 2)):
        palette = []
        offset = pi * (PAL_COLORS * 2)
        # iterate through every color in palette
        for ci in range(PAL_COLORS):
            val = struct.unpack_from("<H", data, offset + (ci * 2))[0]
            # 0xff is opaque, 0x00 is transparent
            A = 0xff if not (val & ALPHA_MASK) else 0x00
            # shift colors into single 5 bit channels, then into 8 bit channels
            R = (val & RED_MASK)   >> 10 << 3
            G = (val & GREEN_MASK) >> 5  << 3
            B = (val & BLUE_MASK)  << 3
            palette.append((R, G, B, A))
        palettes.append(palette)
    return palettes


def unpack_6bit(triplets: np.ndarray) -> np.ndarray:
    b0, b1, b2 = triplets[..., 0], triplets[..., 1], triplets[..., 2]
    return np.stack([
        b0 >> 2,
        ((b0 & 0x03) << 4) | (b1 >> 4),
        ((b1 & 0x0F) << 2) | (b2 >> 6),
        b2 & 0x3F,
    ], axis=-1)


def unpack_all_cels(cel_data, len_cel):
    triplets = np.frombuffer(cel_data, dtype=np.uint8, count=len_cel)
    triplets = triplets.reshape(len_cel // CEL_BYTES, -1, 3)
    return unpack_6bit(triplets).reshape(len_cel // CEL_BYTES, CEL_H, CEL_W)


def render_all_frames(cel_data, palettes: np.ndarray, animations: np.ndarray, base_dir: str, frames: bool, gifs: bool, fulls: bool, palette_swap: str):
    len_cel = len(cel_data)
    cels = unpack_all_cels(cel_data, len_cel)
    for j, full in enumerate(animations):
        # we will copy canvas of every anim so then we can generate fulls
        layer_canvases: List[Optional[np.ndarray]] = [None] * 8

        for k, anim in enumerate(full):
            frame_list = anim["frames"]
            if len(frame_list) == 0:
                continue
            # this works and gets all cel_index values and flags
            cel_idx = np.array([[t[0] for t in frame] for frame in frame_list], dtype=np.int32)
            flags   = np.array([[t[1] for t in frame] for frame in frame_list], dtype=np.int32)
            # tiles.
            tiles = cels[cel_idx]
            # I LOVE VECTOR MASKS!
            flip_mask = (flags & FLAG_H_FLIP).astype(bool)
            # flipping (makes sense as you look into it)
            tiles[flip_mask] = tiles[flip_mask][:, :, ::-1] # [num_frames, h, w (flipped)]
            # looks cool ngl
            canvas = np.zeros((len(frame_list), 128, 128), dtype=np.uint8)
            canvas[:, 0:CEL_H,   0:CEL_W]   = tiles[:, 0]
            canvas[:, 0:CEL_H,   CEL_W:(CEL_W * 2)] = tiles[:, 1]
            canvas[:, CEL_H:(CEL_H * 2), 0:CEL_W]   = tiles[:, 2]
            canvas[:, CEL_H:(CEL_H * 2), CEL_W:(CEL_W * 2)] = tiles[:, 3]

            # сохраняем для fulls
            layer_canvases[k] = canvas

            palette = palettes[anim["pal_idx"]]

            # as simple as it could get
            if frames:
                out_dir = f"out/frames/{base_dir}/{j:03d}/"
                os.makedirs(out_dir, exist_ok=True)
                for fi in range(len(frame_list)):
                    write_indexed_png(
                        f"{out_dir}{ANIM_TYPES[k]}_{fi:02d}.png",
                        canvas[fi],
                        palette[:, :3],
                        palette[:, 3]
                    )

            # may be a bit cleaner
            if gifs:
                out_dir = f"out/gifs/{base_dir}/{j:03d}/"
                os.makedirs(out_dir, exist_ok=True)

                padded_palette = np.zeros((256, 3), dtype=np.uint8)
                # we will check alpha later
                padded_palette[:PAL_COLORS] = palette[:, :3]
                flat_palette = padded_palette.flatten().tolist()

                # to be exact, right here
                # IT WORKS.
                trans_indices = np.where(palette[:, 3] == 0)[0]
                transparency_val = int(trans_indices[0]) if len(trans_indices) > 0 else None

                # maybe there is a faster way to do this
                pil_frames = []
                for fi in range(len(frame_list)):
                    img = Image.fromarray(canvas[fi], mode='P')
                    img.putpalette(flat_palette)
                    pil_frames.append(img)

                # is this check redundant?
                if pil_frames:
                    gif_path = f"{out_dir}{ANIM_TYPES[k]}.gif"

                    save_args = {
                        "save_all": True,
                        "append_images": pil_frames[1:],
                        "duration": 66,
                        "loop": 0,
                        "transparency": transparency_val,
                        # these two are VERY important, or the image would be a bit broken
                        "disposal": 2,
                        "optimize": False
                    }

                    pil_frames[0].save(gif_path, **save_args)

        if fulls:
            if j == 0 and DO_NOT_GENERATE_ANIM_0_IF_CREATING_FULLS: continue
            out_dir = f"out/fulls/{base_dir}/"
            os.makedirs(out_dir, exist_ok=True)

            # palette
            unified_palette = np.zeros((256, 4), dtype=np.uint8)

            # always (4*2) layers in a full
            for i in range(8):
                # a neat trick to get the layer
                layer_i = i // 2
                # and the palette
                pal_offset = layer_i * PAL_COLORS
                # set palettes
                unified_palette[pal_offset: pal_offset + PAL_COLORS] = palettes[full[i]["pal_idx"]]

            # yeah it WORKS, probably needs changing tho
            valid: List[np.ndarray] = []
            for c in layer_canvases:
                if c is not None and c.shape[0] > 0:
                    valid.append(c)

            if not valid:
                continue

            num_frames = max(c.shape[0] for c in valid)

            # index 0 will ALWAYS be transparent (as well as 64, 128 and 192, but for GIF it's only one)
            full_frames = []
            for fi in range(num_frames):
                new_canvas = np.zeros((128, FULL_WIDTH), dtype=np.uint8)

                # one more time
                for i in range(8):
                    layer_canvas = layer_canvases[i]
                    if layer_canvas is None or layer_canvas.shape[0] == 0:
                        continue

                    # if a layer has fewer frames than the longest one, freeze the last one (maybe an edge case)
                    src_fi = min(fi, layer_canvas.shape[0] - 1)
                    tile = layer_canvas[src_fi]

                    layer_i = i // 2
                    pal_offset = layer_i * PAL_COLORS
                    # right or left
                    x_shift = 0 if (i % 2 == 1) else (FULL_WIDTH - 128)

                    # local index 0 is the transparency inside palette block of this layer
                    mask = tile != 0
                    dest = new_canvas[:, x_shift:x_shift + 128]
                    dest[mask] = tile[mask] + pal_offset

                full_frames.append(new_canvas)

            flat_palette = unified_palette[:, :3].flatten().tolist()
            pil_full_frames = []
            for fc_arr in full_frames:
                img = Image.fromarray(fc_arr, mode='P')
                img.putpalette(flat_palette)
                pil_full_frames.append(img)

            gif_path = f"{out_dir}{j:03d}_full.gif"
            pil_full_frames[0].save(
                gif_path,
                save_all=True,
                append_images=pil_full_frames[1:],
                duration=66,
                loop=0,
                transparency=0,
                # everything will break if we don't do this two
                disposal=2,
                optimize=False,
            )