"""Minimal QR encoder for the LAN session URL. No third-party dependency."""
from __future__ import annotations

# GF(256) for QR Reed-Solomon. Primitive polynomial 0x11d.
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]

# version -> (total_codewords, ecc_codewords) for ECC level M
_VERSION_M = {
    1: (26, 10),
    2: (44, 16),
    3: (70, 26),
    4: (100, 36),
    5: (134, 48),
    6: (172, 64),
    7: (196, 72),
    8: (242, 88),
    9: (292, 110),
    10: (346, 130),
}
_ALIGN = {
    2: (6, 18),
    3: (6, 22),
    4: (6, 26),
    5: (6, 30),
    6: (6, 34),
    7: (6, 22, 38),
    8: (6, 24, 42),
    9: (6, 26, 46),
    10: (6, 28, 50),
}


def _gf_mul(a, b):
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def _rs_generator(nsym):
    g = [1]
    for i in range(nsym):
        next_g = [0] * (len(g) + 1)
        for j, coef in enumerate(g):
            next_g[j] ^= _gf_mul(coef, _EXP[i])
            next_g[j + 1] ^= coef
        g = next_g
    return g


def _rs_encode(data, nsym):
    gen = _rs_generator(nsym)
    ecc = [0] * nsym
    for byte in data:
        factor = byte ^ ecc[0]
        ecc = ecc[1:] + [0]
        for i, coef in enumerate(gen[1:]):
            ecc[i] ^= _gf_mul(factor, coef)
    return ecc


def _needed_version(payload_len):
    bits = 4 + 8 + payload_len * 8 + 4
    for version, (total, ecc) in _VERSION_M.items():
        capacity = (total - ecc) * 8
        if bits <= capacity:
            return version
    raise ValueError("URL is too long for the local QR encoder")


def _encode_bytes(data, version):
    total, ecc = _VERSION_M[version]
    data_capacity = total - ecc
    bits = [0, 1, 0, 0]
    bits.extend(int(bit) for bit in f"{len(data):08b}")
    for byte in data:
        bits.extend(int(bit) for bit in f"{byte:08b}")
    bits.extend([0] * min(4, data_capacity * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)
    codewords = []
    for i in range(0, len(bits), 8):
        value = 0
        for bit in bits[i:i + 8]:
            value = (value << 1) | bit
        codewords.append(value)
    pad = (0xEC, 0x11)
    index = 0
    while len(codewords) < data_capacity:
        codewords.append(pad[index % 2])
        index += 1
    return codewords + _rs_encode(codewords, ecc)


def _size(version):
    return 21 + 4 * (version - 1)


def _reserve(version):
    n = _size(version)
    reserved = [[False] * n for _ in range(n)]

    def fill(r0, c0, h, w):
        for r in range(r0, r0 + h):
            for c in range(c0, c0 + w):
                if 0 <= r < n and 0 <= c < n:
                    reserved[r][c] = True

    for r, c in ((0, 0), (0, n - 7), (n - 7, 0)):
        fill(r, c, 7, 7)
        fill(r - 1, c - 1, 9, 9)
    for i in range(n):
        reserved[6][i] = True
        reserved[i][6] = True
    for r in _ALIGN.get(version, ()):
        for c in _ALIGN.get(version, ()):
            if reserved[r][c] and (r, c) in ((6, 6),):
                continue
            if (r < 9 and c < 9) or (r < 9 and c > n - 10) or (r > n - 10 and c < 9):
                continue
            fill(r - 2, c - 2, 5, 5)
    fill(8, 0, 1, 9)
    fill(0, 8, 9, 1)
    fill(8, n - 8, 1, 8)
    fill(n - 8, 8, 8, 1)
    if version >= 7:
        fill(0, n - 11, 6, 3)
        fill(n - 11, 0, 3, 6)
    return reserved


def _place_finders(matrix, n):
    pattern = (
        "1111111"
        "1000001"
        "1011101"
        "1011101"
        "1011101"
        "1000001"
        "1111111"
    )

    def stamp(r0, c0):
        for i, bit in enumerate(pattern):
            matrix[r0 + i // 7][c0 + i % 7] = bit == "1"
        for r in range(r0 - 1, r0 + 8):
            for c in range(c0 - 1, c0 + 8):
                if 0 <= r < n and 0 <= c < n and not (r0 <= r < r0 + 7 and c0 <= c < c0 + 7):
                    matrix[r][c] = False

    stamp(0, 0)
    stamp(0, n - 7)
    stamp(n - 7, 0)


def _place_align(matrix, version):
    positions = _ALIGN.get(version, ())
    n = len(matrix)
    for r in positions:
        for c in positions:
            if (r < 9 and c < 9) or (r < 9 and c > n - 10) or (r > n - 10 and c < 9):
                continue
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    matrix[r + dr][c + dc] = max(abs(dr), abs(dc)) != 1


def _place_timing(matrix):
    n = len(matrix)
    for i in range(n):
        matrix[6][i] = i % 2 == 0
        matrix[i][6] = i % 2 == 0


def _place_data(matrix, reserved, codewords, mask):
    n = len(matrix)
    bits = []
    for byte in codewords:
        bits.extend(int(bit) for bit in f"{byte:08b}")
    index = 0

    def masked(r, c, bit):
        if mask == 0:
            invert = (r + c) % 2 == 0
        elif mask == 1:
            invert = r % 2 == 0
        else:
            invert = (r + c) % 3 == 0
        return bit ^ invert

    col = n - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(n - 1, -1, -1) if upward else range(n)
        for row in rows:
            for dc in (0, -1):
                c = col + dc
                if reserved[row][c]:
                    continue
                bit = bits[index] if index < len(bits) else 0
                matrix[row][c] = masked(row, c, bit)
                index += 1
        col -= 2
        upward = not upward


def _format_bits(mask):
    data = (0b00 << 3) | mask  # ECC M = 00
    value = data << 10
    poly = 0b10100110111
    for i in range(14, 9, -1):
        if value & (1 << i):
            value ^= poly << (i - 10)
    bits = ((data << 10) | value) ^ 0b101010000010010
    return f"{bits:015b}"


def _place_format(matrix, mask):
    bits = _format_bits(mask)
    n = len(matrix)
    coords_a = [(8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5), (8, 7), (8, 8),
                (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8)]
    coords_b = [(n - 1, 8), (n - 2, 8), (n - 3, 8), (n - 4, 8), (n - 5, 8), (n - 6, 8), (n - 7, 8),
                (8, n - 8), (8, n - 7), (8, n - 6), (8, n - 5), (8, n - 4), (8, n - 3), (8, n - 2), (8, n - 1)]
    for bit, (r, c), (r2, c2) in zip(bits, coords_a, coords_b):
        matrix[r][c] = bit == "1"
        matrix[r2][c2] = bit == "1"
    matrix[n - 8][8] = True


def encode_matrix(text):
    data = text.encode("utf-8")
    version = _needed_version(len(data))
    n = _size(version)
    codewords = _encode_bytes(data, version)
    reserved = _reserve(version)
    matrix = [[False] * n for _ in range(n)]
    _place_finders(matrix, n)
    _place_align(matrix, version)
    _place_timing(matrix)
    matrix[8][8] = False
    mask = 0
    _place_data(matrix, reserved, codewords, mask)
    _place_format(matrix, mask)
    return matrix


def render_ascii(text):
    matrix = encode_matrix(text)
    quiet = 2
    n = len(matrix) + quiet * 2
    padded = [[False] * n for _ in range(n)]
    for r, row in enumerate(matrix):
        for c, bit in enumerate(row):
            padded[r + quiet][c + quiet] = bit
    lines = []
    for r in range(0, n, 2):
        row = []
        upper = padded[r]
        lower = padded[r + 1] if r + 1 < n else [False] * n
        for u, d in zip(upper, lower):
            if u and d:
                row.append("█")
            elif u:
                row.append("▀")
            elif d:
                row.append("▄")
            else:
                row.append(" ")
        lines.append("".join(row))
    return "\n".join(lines)
