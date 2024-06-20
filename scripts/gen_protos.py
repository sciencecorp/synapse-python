#!/usr/bin/env python
import os
import sys
from importlib import resources
from grpc_tools import protoc


def _get_resource_file_name(
    package_or_requirement: str, resource_name: str
) -> str:
    """Obtain the filename for a resource on the file system."""
    file_name = None
    if sys.version_info >= (3, 9, 0):
        file_name = (
            resources.files(package_or_requirement) / resource_name
        ).resolve()
    return str(file_name)

def build_package_protos(package_root, output_dir, strict_mode=False):
    proto_files = []
    inclusion_root = os.path.abspath(package_root)
    output_root = os.path.abspath(output_dir)
    for root, _, files in os.walk(inclusion_root):
        for filename in files:
            if filename.endswith(".proto"):
                proto_files.append(
                    os.path.abspath(os.path.join(root, filename))
                )

    well_known_protos_include = _get_resource_file_name("grpc_tools", "_proto")

    for proto_file in proto_files:
        command = [
            "grpc_tools.protoc",
            "--proto_path={}".format(inclusion_root),
            "--proto_path={}".format(well_known_protos_include),
            "--python_out={}".format(output_root),
            "--pyi_out={}".format(output_root),
            "--grpc_python_out={}".format(output_root),
        ] + [proto_file]
        if protoc.main(command) != 0:
            if strict_mode:
                raise Exception("error: {} failed".format(command))
            else:
                sys.stderr.write("warning: {} failed".format(command))


if __name__ == '__main__':
    build_package_protos("./synapse-api/api", "./proto", strict_mode=True)