"""Validate release metadata and package contents without importing Endstone."""
from email.parser import Parser
from pathlib import Path
import tomllib
from zipfile import ZipFile

project = tomllib.loads(Path("pyproject.toml").read_text())["project"]
wheels = list(Path("dist").glob("*.whl"))
assert len(wheels) == 1, wheels
wheel = wheels[0]
assert wheel.name == f"endstone_u_dynamic_light-{project['version']}-py3-none-any.whl", wheel.name
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
    for filename in ("__init__.py", "u_dynamic_light.py", "lang.py"):
        assert f"endstone_u_dynamic_light/{filename}" in names, filename
    metadata_files = [name for name in names if name.endswith(".dist-info/METADATA")]
    assert len(metadata_files) == 1, metadata_files
    metadata = Parser().parsestr(archive.read(metadata_files[0]).decode("utf-8"))
    assert metadata["Name"] == project["name"], metadata["Name"]
    assert metadata["Version"] == project["version"], metadata["Version"]
    assert set(metadata["Requires-Python"].split(",")) == {">=3.11", "<3.16"}, metadata["Requires-Python"]
    assert metadata.get_all("Requires-Dist") == ["mcbe-binarystream==2.1.0"], metadata.get_all("Requires-Dist")
    entries = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
    assert len(entries) == 1, entries
    entry_points = archive.read(entries[0]).decode("utf-8")
    assert "[endstone]" in entry_points, entry_points
    assert "u_dynamic_light = endstone_u_dynamic_light:u_dynamic_light" in entry_points, entry_points
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names), names
print(f"Verified {wheel}: Python {metadata['Requires-Python']}; {metadata['Requires-Dist']}")
