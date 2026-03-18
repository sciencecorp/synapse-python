#!/usr/bin/env python3
"""ONNX to DLC conversion script.

Runs inside the synapse-model-converter Docker container.
Expects:
  - SNPE/QAIRT SDK mounted at the path given by --snpe-root
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
# ONNX transforms (SNPE compatibility)
# ---------------------------------------------------------------------------

def fix_gemm_transpose(onnx_path, output_path=None):
    """Convert GEMM ops with transB=1 to MatMul+Add."""
    import onnx
    from onnx import helper, numpy_helper

    model = onnx.load(onnx_path)
    graph = model.graph
    if output_path is None:
        output_path = onnx_path

    replacements = []
    initializers_to_add = []
    transforms_applied = 0

    for idx, node in enumerate(graph.node):
        if node.op_type != "Gemm":
            continue

        trans_b = 0
        alpha = 1.0
        beta = 1.0
        trans_a = 0

        for attr in node.attribute:
            if attr.name == "transB":
                trans_b = attr.i
            elif attr.name == "transA":
                trans_a = attr.i
            elif attr.name == "alpha":
                alpha = attr.f
            elif attr.name == "beta":
                beta = attr.f

        if trans_b != 1:
            continue
        if trans_a != 0 or alpha != 1.0:
            print(f"Warning: Skipping complex GEMM node {node.name}")
            continue

        weight_name = node.input[1]
        weight_initializer = None
        for init in graph.initializer:
            if init.name == weight_name:
                weight_initializer = init
                break

        if weight_initializer is None:
            print(f"Warning: Could not find initializer for {weight_name}, skipping")
            continue

        transforms_applied += 1
        weight_array = numpy_helper.to_array(weight_initializer)
        transposed_weight = weight_array.T
        new_weight_name = f"{weight_name}_transposed"
        new_weight = numpy_helper.from_array(transposed_weight, name=new_weight_name)
        initializers_to_add.append(new_weight)

        matmul_output = f"{node.name}_matmul_out"
        matmul_node = helper.make_node(
            "MatMul",
            inputs=[node.input[0], new_weight_name],
            outputs=[matmul_output],
            name=f"{node.name}_matmul",
        )

        if len(node.input) > 2 and node.input[2]:
            bias_name = node.input[2]
            if beta != 1.0:
                for init in graph.initializer:
                    if init.name == bias_name:
                        bias_array = numpy_helper.to_array(init)
                        scaled_bias = bias_array * beta
                        new_bias_name = f"{bias_name}_scaled"
                        new_bias = numpy_helper.from_array(
                            scaled_bias, name=new_bias_name
                        )
                        initializers_to_add.append(new_bias)
                        bias_name = new_bias_name
                        break

            add_node = helper.make_node(
                "Add",
                inputs=[matmul_output, bias_name],
                outputs=node.output,
                name=f"{node.name}_add",
            )
            replacement_nodes = [matmul_node, add_node]
        else:
            matmul_node = helper.make_node(
                "MatMul",
                inputs=[node.input[0], new_weight_name],
                outputs=node.output,
                name=f"{node.name}_matmul",
            )
            replacement_nodes = [matmul_node]

        replacements.append((idx, replacement_nodes))

    if transforms_applied > 0:
        for idx, new_nodes in reversed(replacements):
            del graph.node[idx]
            for i, new_node in enumerate(new_nodes):
                graph.node.insert(idx + i, new_node)
        graph.initializer.extend(initializers_to_add)
        print(f"Applied GEMM->MatMul+Add transformation to {transforms_applied} nodes")
        onnx.save(model, output_path)

    return output_path


def downgrade_opset(onnx_path, target_opset=11, output_path=None):
    """Downgrade ONNX opset version for SNPE compatibility."""
    import onnx
    from onnx import version_converter

    model = onnx.load(onnx_path)
    if output_path is None:
        output_path = onnx_path

    current_opset = model.opset_import[0].version
    if current_opset <= target_opset:
        print(f"Model opset {current_opset} already at or below target {target_opset}")
        return output_path

    print(f"Downgrading opset from {current_opset} to {target_opset}...")
    try:
        converted = version_converter.convert_version(model, target_opset)
        onnx.save(converted, output_path)
        print(f"Successfully downgraded to opset {target_opset}")
    except Exception as e:
        print(f"Warning: Could not downgrade opset: {e}. Proceeding with original.")

    return output_path


# ---------------------------------------------------------------------------
# DLC conversion
# ---------------------------------------------------------------------------

def find_converter(snpe_root):
    path = os.path.join(snpe_root, "bin", "x86_64-linux-clang", "snpe-onnx-to-dlc")
    return path if os.path.exists(path) else None


def convert(input_path, output_path, snpe_root, input_shape=None, input_name=None):
    """Run the full ONNX -> DLC conversion pipeline."""
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

    # Determine input name from model
    if input_name is None:
        shapes = get_input_shapes(input_path)
        input_name = shapes[0][0] if shapes else "input"

    # Work on a temp copy so we don't modify the original
    temp_dir = tempfile.mkdtemp()
    temp_onnx = os.path.join(temp_dir, os.path.basename(input_path))
    shutil.copy2(input_path, temp_onnx)

    # Apply transforms
    print("Applying ONNX transformations...")
    try:
        fix_gemm_transpose(temp_onnx)
    except Exception as e:
        print(f"Warning: GEMM transform failed: {e}. Proceeding.")

    try:
        downgrade_opset(temp_onnx)
    except Exception as e:
        print(f"Warning: Opset downgrade failed: {e}. Proceeding.")

    # Find converter
    converter = find_converter(snpe_root)
    if converter is None:
        print(
            f"ERROR: snpe-onnx-to-dlc not found at "
            f"{snpe_root}/bin/x86_64-linux-clang/snpe-onnx-to-dlc",
            file=sys.stderr,
        )
        return False

    # Set up environment for the SNPE converter
    env = os.environ.copy()
    env["SNPE_ROOT"] = snpe_root
    env["PYTHONPATH"] = os.path.join(snpe_root, "lib", "python")
    env["LD_LIBRARY_PATH"] = "/usr/local/lib:/usr/lib/x86_64-linux-gnu"

    cmd = [
        sys.executable,
        converter,
        "--input_network",
        temp_onnx,
        "--output_path",
        output_path,
    ]

    if input_shape is not None:
        shape_str = ",".join(str(d) for d in input_shape)
        cmd.extend(["-d", input_name, shape_str])

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)

    shutil.rmtree(temp_dir, ignore_errors=True)

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
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert ONNX model to Qualcomm DLC format"
    )
    parser.add_argument("--input", required=True, help="Path to input ONNX model")
    parser.add_argument("--output", required=True, help="Path for output DLC file")
    parser.add_argument(
        "--snpe-root", required=True, help="Path to SNPE/QAIRT SDK root"
    )
    parser.add_argument(
        "--input-shape", default=None, help="Input shape (comma-separated, e.g. 1,1920)"
    )
    parser.add_argument("--input-name", default=None, help="Input tensor name")
    args = parser.parse_args()

    input_shape = None
    if args.input_shape:
        input_shape = tuple(int(x.strip()) for x in args.input_shape.split(","))

    success = convert(
        args.input,
        args.output,
        args.snpe_root,
        input_shape=input_shape,
        input_name=args.input_name,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
