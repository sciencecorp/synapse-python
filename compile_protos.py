import os
import shutil
import subprocess
import glob

PROJECT_NAME = "synapsectl"
PROTOC = "python -m grpc_tools.protoc"
PROTO_DIR = "./synapse-api"
PROTO_OUT = "./synapse"

def remove_path(path):
    if os.path.isfile(path) or os.path.islink(path):
        os.remove(path)
    elif os.path.isdir(path):
        shutil.rmtree(path)

def clean():
    if os.path.exists("bin"):
        shutil.rmtree("bin", ignore_errors=True)
    for file in glob.glob(os.path.join(PROTO_OUT, "api*")):
        try:
            remove_path(file)
        except PermissionError:
            print(f"Warning: Unable to remove {file}. It may be in use.")

def generate():
    os.makedirs("bin", exist_ok=True)
    os.makedirs(PROTO_OUT, exist_ok=True)

    protos = [os.path.relpath(proto, PROTO_DIR) for proto in glob.glob(os.path.join(PROTO_DIR, "**", "*.proto"), recursive=True)]
    protos = [proto.replace(os.sep, '/') for proto in protos]  # Ensure forward slashes

    descriptor_cmd = f'{PROTOC} -I={PROTO_DIR} --descriptor_set_out=bin/descriptors.binpb {" ".join(protos)}'
    print(f"Running command: {descriptor_cmd}")
    subprocess.run(descriptor_cmd, shell=True, check=True)

    python_cmd = f'{PROTOC} -I={PROTO_DIR} --python_out={PROTO_OUT} {" ".join(protos)}'
    print(f"Running command: {python_cmd}")
    subprocess.run(python_cmd, shell=True, check=True)

    grpc_cmd = f'{PROTOC} -I={PROTO_DIR} --grpc_python_out={PROTO_OUT} api/synapse.proto'
    print(f"Running command: {grpc_cmd}")
    subprocess.run(grpc_cmd, shell=True, check=True)

    protol_cmd = f'protol --create-package --in-place --python-out {PROTO_OUT} raw bin/descriptors.binpb'
    print(f"Running command: {protol_cmd}")
    subprocess.run(protol_cmd, shell=True, check=True)

def main():
    clean()
    generate()

if __name__ == "__main__":
    main()