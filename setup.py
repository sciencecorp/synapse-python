from setuptools import setup, find_packages, Extension
from Cython.Build import cythonize
from pathlib import Path
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

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

extensions = [
    Extension(
        "synapse.utils.ndtp",
        ["synapse/utils/ndtp.pyx"],
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="science-synapse",
    version="0.11.0",
    description="Client library and CLI for the Synapse API",
    author="Science Team",
    author_email="team@science.xyz",
    packages=find_packages(include=["synapse", "synapse.*"]),
    long_description=long_description,
    long_description_content_type="text/markdown",
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
    python_requires=">=3.9",
    install_requires=[
        "coolname",
        "grpcio-tools",
        "protoletariat",
        "numpy >=2.0.0",
        "pyserial",
        "scipy",
        "crcmod",
        "rich",
        "pyqtgraph",
        "pyqt5",
        "pandas >=2.2.0",
        "dearpygui",
        "pyzmq"
    ],
    entry_points={
        "console_scripts": [
            "synapsectl = synapse.cli:main",
            "synapse-sim = synapse.simulator:main",
        ],
    },
)
