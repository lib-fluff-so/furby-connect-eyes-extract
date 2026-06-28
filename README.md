# Furby Connect SPR/CEL/PAL converter
A simple python project to convert Furby Connect's graphical assets to PNGs and/or GIFs

![Furby connect eye](out/Furby/Furby-Files/Furby-NAND/Personalities/Base/fulls/full_anim_0002.gif)

![Furby connect DJ eye](out/Furby/Furby-Files/Furby-NAND/Personalities/DJ/fulls/full_anim_0001.gif)

## Extracted assets **for _all_ six personalities** (Base, Cat, DJ, Ninja, Pirate, PopStar, Princess) are in the out/Furby/Furby-Files/Furby-NAND/Personalities/[PersonalityName]/fulls folder!

| Personality | Animations |
|:------------|:-----------|
| Base        | 156        |
| Cat         | 8          | 
| DJ          | 9          |
| Ninja       | 7          |
| Pirate      | 14         |
| Popstar     | 9          |
| Princess    | 8          |

I think the reason all personalities other from Base have so little animations is that they don't repeat all the base's animations in a different color, but rather just change the palette in runtime to save space.

Even knowing that, it's sad Hasbro bundled so little animations in those additional personalities.

<details>
    <summary>Things for developers</summary>

If you want to use this script, 
- Clone the repo using `git clone https://github.com/lib-fluff-so/furby-connect-eyes-extract`
- Do `git submodule update --init --recursive`
- install numpy, tqdm and Pillow using `pip install numpy tqdm Pillow`

```
usage: main.py [-h] [--frames |
               --no-frames] [--videos | --no-videos] [--fulls | --no-fulls]
               [--anim-dump-count N]
               folders [folders ...]
```

Everything should be straight-forward

For example, 
`python main.py Furby/Furby-Files/Furby-NAND/Personalities/Base Furby/Furby-Files/Furby-NAND/Personalities/Cat Furby/Furby-Files/Furby-NAND/Personalities/DJ Furby/Furby-Files/Furby-NAND/Personalities/Ninja Furby/Furby-Files/Furby-NAND/Personalities/Pirate Furby/Furby-Files/Furby-NAND/Personalities/PopStar Furby/Furby-Files/Furby-NAND/Personalities/Princess --videos --fulls`
will dump videos (GIFs) and fulls (the whole eye composition) from all the Personalities (assuming you have submodules installed).
</details>

### Huge thanks to
- https://github.com/Furby-ReConnect/Furby -- Furby files extracted from NAND dump
- https://github.com/micheal65536/furbhax -- Furby Connect FTL reverse engineering
- https://github.com/swarley7/furbhax -- Initial and the only Furby Connect NAND dump on the internet
- https://github.com/ctxis/Furby -- Original Furby repository, this code just uses its algorithms to parse standalone CEL, SPR and PAL files instead of sections in DLC and also saves them to GIFs

_Furby and all of extracted files are the property of Hasbro. The author of this repository does not own these assets. This tool is non-commercial and fan-made._
