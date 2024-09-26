import os
import subprocess
import sys
from setuptools import setup, Extension, find_packages
from setuptools.command.build_ext import build_ext


class CMakeExtension(Extension):
    def __init__(self, name, sourcedir=""):
        Extension.__init__(self, name, sources=[])
        self.sourcedir = os.path.abspath(sourcedir)


class CMakeBuild(build_ext):
    def build_extension(self, ext):
        extdir = os.path.abspath(os.path.dirname(self.get_ext_fullpath(ext.name)))

        cmake_args = [
            f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={extdir}",
            f"-DPYTHON_EXECUTABLE={sys.executable}",
            f'-DCMAKE_BUILD_TYPE={"Debug" if self.debug else "Release"}',
        ]

        build_args = ["--config", "Debug" if self.debug else "Release"]

        if not os.path.exists(self.build_temp):
            os.makedirs(self.build_temp)

        subprocess.check_call(
            ["cmake", ext.sourcedir] + cmake_args, cwd=self.build_temp
        )
        subprocess.check_call(
            ["cmake", "--build", "."] + build_args, cwd=self.build_temp
        )


# Get the absolute path to the libndtp directory
libndtp_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "libndtp"))

setup(
    name="synapse",
    version="0.1.0",
    packages=find_packages(exclude=["config", "data"]),
    ext_modules=[CMakeExtension("libndtp", sourcedir=libndtp_path)],
    cmdclass=dict(build_ext=CMakeBuild),
    install_requires=["grpcio-tools", "protoletariat", "pyserial"],
    entry_points={
        "console_scripts": [
            "synapsectl=synapse.cli:main",
            "synapse-sim=synapse.simulator:main",
        ],
    },
)
