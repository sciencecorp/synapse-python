from setuptools import setup, Extension
from Cython.Build import cythonize
import os

extra_compile_args = []
if os.name == "nt":  # Windows
    extra_compile_args = ["/w"]
else:  # macOS and Linux
    extra_compile_args = [
        "-Wno-unreachable-code",
        "-Wno-unreachable-code-fallthrough",
        "-O3",
    ]

extensions = [
    Extension(
        "synapse.utils.ndtp",
        ["synapse/utils/ndtp.pyx"],
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
)
