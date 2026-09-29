"""setup.py — person_tracker_native の pybind11 build entry。

A1 (preprocess + detector) では実 binding は無いため、本ファイルは
A3 で bindings.cpp が入った後の build を想定した skaffold。

実体ビルドは CMake driven (CMakeLists.txt) で、本 setup.py は
``pip install -e .`` 経由で cmake を呼ぶ薄ラッパに留める。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from setuptools import setup, Extension
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    def __init__(self, name: str, sourcedir: str = "") -> None:
        super().__init__(name, sources=[])
        self.sourcedir = str(Path(sourcedir).resolve())


class CMakeBuild(build_ext):
    def build_extension(self, ext: CMakeExtension) -> None:  # type: ignore[override]
        build_temp = Path(self.build_temp).resolve()
        build_temp.mkdir(parents=True, exist_ok=True)
        ext_full = Path(self.get_ext_fullpath(ext.name)).resolve()
        ext_dir = ext_full.parent
        ext_dir.mkdir(parents=True, exist_ok=True)

        cfg = "Release"
        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={ext_dir}",
            f"-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={ext_dir}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
            f"-DCMAKE_BUILD_TYPE={cfg}",
        ]
        build_args = ["--config", cfg, "--parallel"]
        if sys.platform == "win32":
            cmake_args += ["-G", "Visual Studio 17 2022", "-A", "x64"]

        subprocess.check_call(
            ["cmake", ext.sourcedir, *cmake_args], cwd=build_temp
        )
        subprocess.check_call(
            ["cmake", "--build", ".", *build_args], cwd=build_temp
        )


setup(
    name="person_tracker_native",
    version="0.1.0",
    description="C++ runtime for PersonTracker (CUDA preprocess + ORT TRT + ByteTracker)",
    ext_modules=[CMakeExtension("person_tracker_native_ext", sourcedir=".")],
    cmdclass={"build_ext": CMakeBuild},
    zip_safe=False,
    python_requires=">=3.10",
)
