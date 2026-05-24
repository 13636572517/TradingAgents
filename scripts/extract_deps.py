"""Extract all dependencies from pyproject.toml → requirements.txt.

Used by Dockerfile.prod to pre-install deps in a separate layer so that
source-code changes do not trigger package re-downloads.
"""
import tomllib

with open("pyproject.toml", "rb") as f:
    d = tomllib.load(f)

proj = d.get("project", {})
deps: list[str] = list(proj.get("dependencies", []))
for extra_deps in proj.get("optional-dependencies", {}).values():
    deps.extend(extra_deps)

with open("requirements.txt", "w") as f:
    f.write("\n".join(deps) + "\n")

print(f"Wrote {len(deps)} dependencies to requirements.txt")
