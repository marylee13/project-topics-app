from pathlib import Path
_base = Path(__file__).parent
_code = "".join((_base / f"logic_src_{i}.py").read_text(encoding="utf-8") for i in range(4))
exec(compile(_code, "logic.py", "exec"), globals())
