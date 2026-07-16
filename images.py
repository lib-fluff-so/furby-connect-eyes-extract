import struct
import zlib
import numpy as np


def write_indexed_png(path, indices, palette_rgb, alpha):
    h, w = indices.shape

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 3, 0, 0, 0))
    plte = chunk(b"PLTE", palette_rgb.astype(np.uint8).tobytes())
    trns = chunk(b"tRNS", alpha.astype(np.uint8).tobytes())

    filtered = np.zeros((h, w + 1), dtype=np.uint8)
    filtered[:, 1:] = indices
    idat = chunk(b"IDAT", zlib.compress(filtered.tobytes(), level=0))
    iend = chunk(b"IEND", b"")

    with open(path, "wb") as f:
        f.write(sig + ihdr + plte + trns + idat + iend)