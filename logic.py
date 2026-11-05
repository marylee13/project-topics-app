# Stage 3 logic loader
import zlib, base64
from pathlib import Path
_chunks = []
_chunks.append(Path(__file__).with_name("logic_data_0.txt").read_text().strip())
_chunks.append(Path(__file__).with_name("logic_data_1.txt").read_text().strip())
_chunks.append(Path(__file__).with_name("logic_data_2.txt").read_text().strip())
_chunks.append(Path(__file__).with_name("logic_data_3.txt").read_text().strip())

_DATA = "".join(_chunks)
exec(compile(zlib.decompress(base64.b64decode(_DATA)), "logic.py", "exec"), globals())
