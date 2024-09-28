# setup.py
from Cython.Build import cythonize
from setuptools import Extension, setup

extensions = [
    Extension(
        "ndtp",
        ["ndtp.pyx"],
        extra_compile_args=[
            "-Wno-unreachable-code",
            "-Wno-unreachable-code-fallthrough",
        ],
    ),
]

setup(
    name="your_package_name",
    ext_modules=cythonize(extensions, compiler_directives={"language_level": "3"}),
)
