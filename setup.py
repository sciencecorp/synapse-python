from setuptools import setup, find_packages, Extension
from Cython.Build import cythonize
import os

extra_compile_args = []
if os.name == "nt":  # Windows
    extra_compile_args = ["/w"]
else:  # macOS and Linux
    extra_compile_args = [
        "-Wno-unreachable-code",
        "-Wno-unreachable-code-fallthrough",
    ]

extensions = [
    Extension(
        "synapse.utils.ndtp",
        ["synapse/utils/ndtp.pyx"],
        extra_compile_args=extra_compile_args,
    ),
]

setup(
    name="synapse",
    version="0.1.0",
    description="Client library and CLI for the Synapse API",
    author="Science Team",
    author_email="team@science.xyz",
    packages=find_packages(include=["synapse", "synapse.*"]),
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
    install_requires=[
        "grpcio-tools",
        "protoletariat",
        "pyserial",
    ],
    entry_points={
        "console_scripts": [
            "synapsectl = synapse.cli:main",
            "synapse-sim = synapse.simulator:main",
        ],
    },
)
