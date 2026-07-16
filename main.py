#!/usr/bin/env python3
"""
Furby Connect SPR/CEL/PAL renderer
"""

import argparse
import resource
import numpy as np
from pathlib import Path
from timed import timed, set_start_time, print_time_status
from parsers import parse_spr, parse_pal, render_all_frames, CEL_BYTES


palette_swapping_base = {
    "BASE": 8, # default blue one
    "CAT": 5,
    "DJ": 2,
    "NINJA": 3,
    "PIRATE": 4,
    "POPSTAR": 6,
    "PRINCESS": 1
}

palette_swapping_personality = {
    "BASE": 8,
    "CAT": 1,
    "DJ": 1,
    "NINJA": 1,
    "PIRATE": 1,
    "POPSTAR": 1,
    "PRINCESS": 1
}


def main():
    # args
    parser = argparse.ArgumentParser(description="Furby Connect eye renderer")
    png_group = parser.add_mutually_exclusive_group()
    png_group.add_argument("--frames", dest="frames", action="store_true", help="Render PNGs")
    png_group.add_argument("--no-frames", dest="frames", action="store_false", help="Do not render PNGs")
    gif_group = parser.add_mutually_exclusive_group()
    gif_group.add_argument("--gifs", dest="gifs", action="store_true", help="Render GIFs")
    gif_group.add_argument("--no-gifs", dest="gifs", action="store_false", help="Do not render GIFs")
    fulls_group = parser.add_mutually_exclusive_group()
    fulls_group.add_argument("--fulls", dest="fulls", action="store_true", help="Render composite 300x128 full GIFs")
    fulls_group.add_argument("--no-fulls", dest="fulls", action="store_false", help="Do not render composite full GIFs")
    parser.set_defaults(frames=False, videos=True, fulls=True)
    parser.add_argument("--anim-dump-count", type=int, default=None, metavar="N",
                        help="Only dump first N animations")
    parser.add_argument("--palette-swapping", choices=["none", "no-repeat", "full"], default="no-repeat", dest="palette_swap")
    parser.add_argument("folders", nargs="+", help="Folder containing .SPR .CEL .PAL files")
    args = parser.parse_args()

    set_start_time()

    def find_file(folder, ext):
        for file in folder.iterdir():
            if file.is_file() and file.suffix.upper() == ext.upper():
                return file
        raise FileNotFoundError(f"No {ext} file in {folder}")

    def load_personality(folder):
        with timed("open files"):
            spr_path = find_file(folder, ".SPR")
            cel_path = find_file(folder, ".CEL")
            pal_path = find_file(folder, ".PAL")
            # load files into RAM and read them, then unload
            with open(spr_path, "rb") as f: spr_data = f.read()
            with open(cel_path, "rb") as f: cel_data = f.read()
            with open(pal_path, "rb") as f: pal_data = f.read()

        with timed("parse PAL and SPR"):
            palettes = np.array(parse_pal(pal_data), dtype=np.uint8)
            animations = parse_spr(spr_data)

        return cel_data, palettes, animations

    def swap_eye_palettes(animations, value):
        # create a flattened view so we can change something easily
        flat_anims = animations.ravel()
        # create a vector mask for eyes in every full
        mask = (np.arange(len(flat_anims)) % 8) < 2
        # change every palette to value if the value in mask is True, this approach works
        for item in flat_anims[mask]:
            item['pal_idx'] = value
        # because flat_anims is a view, animations are now correct!

    # "full" mode re-renders BASE's own animations once per non-base personality
    # (just with a different eye palette), so preload BASE's data a single time up front
    base_cel_data = base_palettes = base_animations = None
    if args.palette_swap == "full":
        base_folder = next((Path(f) for f in args.folders if Path(f).name.upper() == "BASE"), None)
        if base_folder is not None:
            base_cel_data, base_palettes, base_animations = load_personality(base_folder)
        else:
            print("Warning: no BASE folder among inputs, skipping base-eye re-render pass")

    for folder in args.folders:
        # pathlib so we are modern
        folder = Path(folder)
        personality_name = folder.name

        cel_data, palettes, animations = load_personality(folder)

        dump_anims = args.anim_dump_count or len(animations)

        print(f"{personality_name}: {len(cel_data) // CEL_BYTES} cels, "
              f"{len(palettes)} palettes, dumping {dump_anims} anims")

        # i.e. "no-repeat" or "full"
        if args.palette_swap != "none":
            with timed("numpy magic"):
                swap_eye_palettes(animations, palette_swapping_personality[personality_name.upper()])
        with timed("render all frames"):
            render_all_frames(cel_data, palettes, animations, personality_name, args.frames, args.gifs, args.fulls, args.palette_swap)

        # "full" mode also dumps a "base" subfolder per non-base personality: it's a full
        # re-render of BASE's OWN animations, just with the eyes recolored per palette_swapping_base
        if args.palette_swap == "full" and personality_name.upper() != "BASE" and base_animations is not None:
            with timed("numpy magic (base variant)"):
                swap_eye_palettes(base_animations, palette_swapping_base[personality_name.upper()])
            with timed("render all frames (base variant)"):
                render_all_frames(base_cel_data, base_palettes, base_animations, f"{personality_name}/base", args.frames, args.gifs, args.fulls, args.palette_swap)

    print_time_status()
    # BUG: reports PyCharm usage when ran from PyCharm instead of the program usage
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"Peak memory usage: {usage / 1024:.2f} MB")

if __name__ == "__main__":
    main()