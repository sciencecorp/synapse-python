from setuptools import setup, find_packages
from pathlib import Path

this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text()

setup(
    name="science-synapse",
    version="2.4.0",
    description="Client library and CLI for the Synapse API",
    author="Science Team",
    author_email="team@science.xyz",
    packages=find_packages(include=["synapse", "synapse.*"]),
    long_description=long_description,
    long_description_content_type="text/markdown",
    python_requires=">=3.9",
    install_requires=[
        "coolname",
        "dearpygui",
        "grpcio-tools",
        "numexpr>=2.8.7",
        "numpy >=2.0.0",
        "pandas >=2.2.0",
        "paramiko >=3.5.1",
        "protoletariat",
        "pyqt5",
        "pyqtgraph",
        "pyserial",
        "pyyaml",
        "pyzmq",
        "rich==14.0.0",
        "scipy",
        "h5py",
    ],
    entry_points={
        "console_scripts": [
            "synapsectl = synapse.cli:main",
            "synapse-sim = synapse.simulator:main",
        ],
    },
)
