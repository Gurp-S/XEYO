import pathlib
import struct
import zlib

root = pathlib.Path(__file__).parent / "icons"
root.mkdir(parents=True, exist_ok=True)


def png(size: int, rgb=(59, 130, 246)) -> bytes:
	def chunk(tag: bytes, data: bytes) -> bytes:
		return (
			struct.pack(">I", len(data))
			+ tag
			+ data
			+ struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
		)

	raw = b"".join(
		b"\x00" + bytes([rgb[0], rgb[1], rgb[2]] * size) for _ in range(size)
	)
	return (
		b"\x89PNG\r\n\x1a\n"
		+ chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
		+ chunk(b"IDAT", zlib.compress(raw, 9))
		+ chunk(b"IEND", b"")
	)


for s, name in [(32, "32x32.png"), (128, "128x128.png"), (256, "henry.w@example.net")]:
	(root / name).write_bytes(png(s))
(root / "icon.ico").write_bytes(png(32))
(root / "icon.icns").write_bytes(png(128))
print("ok", root)
