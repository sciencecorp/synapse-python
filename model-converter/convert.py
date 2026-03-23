#!/usr/bin/env python3
"""ONNX to QNN context binary conversion script.

Runs inside the synapse-model-converter Docker container.
Pipeline: ONNX → qairt-converter → DLC → qairt-quantizer → qnn-context-binary-generator → .bin

Expects:
  - QAIRT SDK mounted at the path given by --snpe-root
  - Input ONNX model accessible at --input
  - Output directory writable at --output parent
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile


# ---------------------------------------------------------------------------
# ONNX helpers
# ---------------------------------------------------------------------------

def get_input_shapes(onnx_path):
    import onnx

    model = onnx.load(onnx_path)
    inputs = []
    for inp in model.graph.input:
        shape = []
        for dim in inp.type.tensor_type.shape.dim:
            if dim.dim_param:
                shape.append(dim.dim_param)
            else:
                shape.append(dim.dim_value)
        inputs.append((inp.name, shape))
    return inputs


def has_dynamic_shapes(onnx_path):
    for _, shape in get_input_shapes(onnx_path):
        for dim in shape:
            if isinstance(dim, str) or dim == 0:
                return True
    return False


# ---------------------------------------------------------------------------
# Tool finders
# ---------------------------------------------------------------------------

def find_tool(snpe_root, name):
    """Find a tool in the SDK bin directory."""
    path = os.path.join(snpe_root, "bin", "x86_64-linux-clang", name)
    return path if os.path.exists(path) else None


def python_env(snpe_root):
    """Environment for running Python-based SDK tools."""
    env = os.environ.copy()
    env["SNPE_ROOT"] = snpe_root
    env["PYTHONPATH"] = os.path.join(snpe_root, "lib", "python")
    env["LD_LIBRARY_PATH"] = "/usr/local/lib:/usr/lib/x86_64-linux-gnu"
    return env


def native_env(snpe_root):
    """Environment for running native (C++) SDK tools."""
    env = os.environ.copy()
    env["SNPE_ROOT"] = snpe_root
    lib_dir = os.path.join(snpe_root, "lib", "x86_64-linux-clang")
    env["LD_LIBRARY_PATH"] = f"{lib_dir}:/usr/local/lib:/usr/lib/x86_64-linux-gnu"
    bin_dir = os.path.join(snpe_root, "bin", "x86_64-linux-clang")
    env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
    return env


# ---------------------------------------------------------------------------
# Step 1: ONNX → DLC (qairt-converter)
# ---------------------------------------------------------------------------

def convert_to_dlc(input_path, output_path, snpe_root, input_shape=None, input_name=None):
    """Convert ONNX model to DLC using qairt-converter."""
    if has_dynamic_shapes(input_path):
        if input_shape is None:
            shapes = get_input_shapes(input_path)
            print("ERROR: Model has dynamic input shapes.", file=sys.stderr)
            print("Current input shapes:", file=sys.stderr)
            for name, shape in shapes:
                print(f"  {name}: {shape}", file=sys.stderr)
            print(
                "\nPlease provide --input-shape with concrete dimensions.",
                file=sys.stderr,
            )
            return False
        print(f"Using provided input shape {input_shape} for dynamic model")

    if input_name is None:
        shapes = get_input_shapes(input_path)
        input_name = shapes[0][0] if shapes else "input"

    # Try qairt-converter first (unified, preferred), fall back to snpe-onnx-to-dlc
    converter = find_tool(snpe_root, "qairt-converter")
    if converter:
        cmd = [
            sys.executable,
            converter,
            "-i", input_path,
            "-o", output_path,
        ]
        if input_shape is not None:
            shape_str = ",".join(str(d) for d in input_shape)
            cmd.extend(["-d", input_name, shape_str])
    else:
        converter = find_tool(snpe_root, "snpe-onnx-to-dlc")
        if converter is None:
            print("ERROR: No converter found (tried qairt-converter, snpe-onnx-to-dlc)",
                  file=sys.stderr)
            return False
        cmd = [
            sys.executable,
            converter,
            "--input_network", input_path,
            "--output_path", output_path,
        ]
        if input_shape is not None:
            shape_str = ",".join(str(d) for d in input_shape)
            cmd.extend(["-d", input_name, shape_str])

    print(f"Converting ONNX to DLC: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=python_env(snpe_root),
                            capture_output=True, text=True, timeout=300)

    if result.returncode != 0:
        print("ERROR: DLC conversion failed:", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.stdout:
            print(result.stdout)
        return False

    if not os.path.exists(output_path):
        print("ERROR: Converter ran but DLC file was not created", file=sys.stderr)
        return False

    print(f"Successfully converted to {output_path}")
    return True


# ---------------------------------------------------------------------------
# Step 2: Quantize DLC (qairt-quantizer)
# ---------------------------------------------------------------------------

def quantize_dlc(dlc_path, input_list, snpe_root, output_path=None):
    """Quantize a DLC model to INT8 using representative input data."""
    # Try qairt-quantizer first, fall back to snpe-dlc-quant
    quantizer = find_tool(snpe_root, "qairt-quantizer")
    if quantizer:
        is_python = True
    else:
        quantizer = find_tool(snpe_root, "snpe-dlc-quant")
        is_python = False
    if quantizer is None:
        print("ERROR: No quantizer found (tried qairt-quantizer, snpe-dlc-quant)",
              file=sys.stderr)
        return False

    if output_path is None:
        base, ext = os.path.splitext(dlc_path)
        output_path = f"{base}_quantized{ext}"

    if is_python:
        cmd = [sys.executable, quantizer, "-i", dlc_path, "-l", input_list,
               "-o", output_path]
        env = python_env(snpe_root)
    else:
        cmd = [quantizer, "--input_dlc", dlc_path, "--input_list", input_list,
               "--output_dlc", output_path]
        env = native_env(snpe_root)

    # The quantizer resolves raw file paths relative to cwd. Create a temp
    # working directory with symlinks so the data mount can stay read-only.
    input_list_dir = os.path.dirname(os.path.abspath(input_list))
    work_dir = tempfile.mkdtemp()
    for name in os.listdir(input_list_dir):
        src = os.path.join(input_list_dir, name)
        dst = os.path.join(work_dir, name)
        os.symlink(src, dst)

    print(f"Quantizing model: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True,
                            timeout=600, cwd=work_dir)

    shutil.rmtree(work_dir, ignore_errors=True)

    if result.returncode != 0:
        print("ERROR: Quantization failed:", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.stdout:
            print(result.stdout)
        return False

    if not os.path.exists(output_path):
        print("ERROR: Quantizer ran but output file not created", file=sys.stderr)
        return False

    # Replace the float DLC with the quantized one
    shutil.move(output_path, dlc_path)
    print(f"Successfully quantized model to {dlc_path}")
    return True


# ---------------------------------------------------------------------------
# Step 3: Generate QNN context binary (qnn-context-binary-generator)
# ---------------------------------------------------------------------------

def generate_context_binary(dlc_path, output_path, snpe_root):
    """Generate a pre-compiled QNN context binary for HTP backend."""
    generator = find_tool(snpe_root, "qnn-context-binary-generator")
    if generator is None:
        print("ERROR: qnn-context-binary-generator not found", file=sys.stderr)
        return False

    backend_lib = os.path.join(snpe_root, "lib", "x86_64-linux-clang", "libQnnHtp.so")
    if not os.path.exists(backend_lib):
        print(f"ERROR: HTP backend not found at {backend_lib}", file=sys.stderr)
        return False

    output_dir = os.path.dirname(output_path)
    output_name = os.path.splitext(os.path.basename(output_path))[0]

    # Write HTP backend extensions config to limit VTCM usage.
    # QCS6490 (Hexagon v68) has limited VTCM; vtcm_mb=0 lets the runtime decide.
    import json

    htp_config_path = os.path.join(output_dir or ".", "htp_config.json")
    with open(htp_config_path, "w") as f:
        json.dump({"graphs": [{"vtcm_mb": 0, "graph_names": ["*"]}]}, f)

    backend_ext_lib = os.path.join(
        snpe_root, "lib", "x86_64-linux-clang", "libQnnHtpNetRunExtensions.so"
    )
    ext_config_path = os.path.join(output_dir or ".", "backend_extensions_config.json")
    with open(ext_config_path, "w") as f:
        json.dump({
            "backend_extensions": {
                "shared_library_path": backend_ext_lib,
                "config_file_path": htp_config_path,
            }
        }, f)

    cmd = [
        generator,
        "--dlc_path", dlc_path,
        "--backend", backend_lib,
        "--binary_file", output_name,
        "--output_dir", output_dir,
        "--config_file", ext_config_path,
    ]

    print(f"Generating context binary: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=native_env(snpe_root),
                            capture_output=True, text=True, timeout=600)

    if result.stdout:
        print(result.stdout)

    if result.returncode != 0:
        print("ERROR: Context binary generation failed:", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        return False

    # qnn-context-binary-generator outputs <name>.bin in output_dir
    expected_bin = os.path.join(output_dir, f"{output_name}.bin")
    if not os.path.exists(expected_bin):
        print(f"ERROR: Expected output not found at {expected_bin}", file=sys.stderr)
        return False

    # Move to the requested output path if different
    if expected_bin != output_path:
        shutil.move(expected_bin, output_path)

    print(f"Successfully generated context binary: {output_path}")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert ONNX model to Qualcomm QNN context binary"
    )
    parser.add_argument("--input", required=True, help="Path to input ONNX model")
    parser.add_argument("--output", required=True, help="Path for output file")
    parser.add_argument(
        "--snpe-root", required=True, help="Path to QAIRT SDK root"
    )
    parser.add_argument(
        "--input-shape", default=None, help="Input shape (comma-separated, e.g. 1,1920)"
    )
    parser.add_argument("--input-name", default=None, help="Input tensor name")
    parser.add_argument(
        "--quantize", action="store_true", help="Quantize model to INT8"
    )
    parser.add_argument(
        "--input-list", default=None, help="Input list file for quantization"
    )
    parser.add_argument(
        "--compile", action="store_true",
        help="Generate QNN context binary (.bin) for HTP backend"
    )
    args = parser.parse_args()

    input_shape = None
    if args.input_shape:
        input_shape = tuple(int(x.strip()) for x in args.input_shape.split(","))

    # Determine intermediate DLC path
    if args.compile:
        dlc_path = os.path.splitext(args.output)[0] + ".dlc"
    else:
        dlc_path = args.output

    # Step 1: Convert ONNX → DLC
    success = convert_to_dlc(
        args.input, dlc_path, args.snpe_root,
        input_shape=input_shape, input_name=args.input_name,
    )

    # Step 2: Quantize (optional, but required for HTP/DSP)
    if success and args.quantize:
        if not args.input_list:
            print("ERROR: --quantize requires --input-list", file=sys.stderr)
            sys.exit(1)
        success = quantize_dlc(dlc_path, args.input_list, args.snpe_root)

    # Step 3: Generate context binary (optional)
    if success and args.compile:
        success = generate_context_binary(dlc_path, args.output, args.snpe_root)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
