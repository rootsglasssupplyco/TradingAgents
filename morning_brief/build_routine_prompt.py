"""Assemble the live routine prompt: ROUTINE_PROMPT.md + the three scripts, verbatim.

The routine runs with no repository attached, so the scripts travel inside its own
instructions (code fetched from elsewhere is blocked by the routine's safety checks).
Usage: python3 build_routine_prompt.py > /tmp/routine_prompt.txt
"""
import ast
import pathlib


def compact(src):
    """Drop docstrings and comments so the routine prompt stays small; behavior is unchanged."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


here = pathlib.Path(__file__).parent
prompt = (here / "ROUTINE_PROMPT.md").read_text().split("\n", 1)[1].rstrip()
parts = [prompt, "", "## Scripts", "Write each block below to the path in its heading, exactly as given."]
for name in ("tv_quotes.py", "tv_track.py", "tv_screen.py"):
    parts += ["", f"### /tmp/{name}", "```python", compact((here / name).read_text()), "```"]
print("\n".join(parts))
