"""ONNX model transformations for SNPE compatibility."""

from typing import Optional

from rich.console import Console


def get_input_shapes(onnx_path: str) -> list[tuple[str, list[int | str]]]:
    """
    Get input shapes from an ONNX model.

    Args:
        onnx_path: Path to the ONNX model

    Returns:
        List of (input_name, shape) tuples where shape may contain strings for dynamic dims
    """
    import onnx

    model = onnx.load(onnx_path)
    inputs = []

    for inp in model.graph.input:
        shape = []
        for dim in inp.type.tensor_type.shape.dim:
            if dim.dim_param:
                shape.append(dim.dim_param)  # Dynamic dimension name
            else:
                shape.append(dim.dim_value)
        inputs.append((inp.name, shape))

    return inputs


def has_dynamic_shapes(onnx_path: str) -> bool:
    """
    Check if an ONNX model has dynamic input shapes.

    Args:
        onnx_path: Path to the ONNX model

    Returns:
        True if any input has dynamic dimensions
    """
    inputs = get_input_shapes(onnx_path)
    for _, shape in inputs:
        for dim in shape:
            if isinstance(dim, str) or dim == 0:
                return True
    return False


def fix_gemm_transpose(
    onnx_path: str,
    output_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> str:
    """
    Convert GEMM ops with transB=1 to MatMul+Add.

    This is a workaround for SNPE converter issues with certain GEMM configurations.

    Args:
        onnx_path: Path to the input ONNX model
        output_path: Path for the output model (defaults to overwriting input)
        console: Rich console for output

    Returns:
        Path to the transformed model
    """
    import onnx
    from onnx import helper, numpy_helper

    model = onnx.load(onnx_path)
    graph = model.graph

    if output_path is None:
        output_path = onnx_path

    # Build list of (node_index, replacement_nodes) to maintain topological order
    replacements = []  # List of (index, [new_nodes])
    initializers_to_add = []
    transforms_applied = 0

    for idx, node in enumerate(graph.node):
        if node.op_type != "Gemm":
            continue

        # Check for transB attribute
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
            continue  # No transformation needed

        if trans_a != 0 or alpha != 1.0:
            # Complex case, skip for now
            if console:
                console.print(
                    f"[yellow]Warning: Skipping complex GEMM node {node.name} "
                    f"(transA={trans_a}, alpha={alpha})[/yellow]"
                )
            continue

        # Get weight tensor and transpose it
        weight_name = node.input[1]
        weight_initializer = None
        for init in graph.initializer:
            if init.name == weight_name:
                weight_initializer = init
                break

        if weight_initializer is None:
            if console:
                console.print(
                    f"[yellow]Warning: Could not find initializer for {weight_name}, "
                    "skipping transformation[/yellow]"
                )
            continue

        transforms_applied += 1

        # Transpose the weight
        weight_array = numpy_helper.to_array(weight_initializer)
        transposed_weight = weight_array.T
        new_weight_name = f"{weight_name}_transposed"
        new_weight = numpy_helper.from_array(transposed_weight, name=new_weight_name)
        initializers_to_add.append(new_weight)

        replacement_nodes = []

        # Create MatMul node
        matmul_output = f"{node.name}_matmul_out"
        matmul_node = helper.make_node(
            "MatMul",
            inputs=[node.input[0], new_weight_name],
            outputs=[matmul_output],
            name=f"{node.name}_matmul",
        )

        # If there's a bias (C input), add it
        if len(node.input) > 2 and node.input[2]:
            bias_name = node.input[2]

            # Handle beta scaling if needed
            if beta != 1.0:
                # Find bias initializer and scale it
                for init in graph.initializer:
                    if init.name == bias_name:
                        bias_array = numpy_helper.to_array(init)
                        scaled_bias = bias_array * beta
                        new_bias_name = f"{bias_name}_scaled"
                        new_bias = numpy_helper.from_array(scaled_bias, name=new_bias_name)
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
            # No bias, MatMul output is the final output
            matmul_node = helper.make_node(
                "MatMul",
                inputs=[node.input[0], new_weight_name],
                outputs=node.output,
                name=f"{node.name}_matmul",
            )
            replacement_nodes = [matmul_node]

        replacements.append((idx, replacement_nodes))

    if transforms_applied > 0:
        # Apply replacements in reverse order to maintain correct indices
        for idx, new_nodes in reversed(replacements):
            del graph.node[idx]
            for i, new_node in enumerate(new_nodes):
                graph.node.insert(idx + i, new_node)

        graph.initializer.extend(initializers_to_add)

        if console:
            console.print(
                f"[green]Applied GEMM→MatMul+Add transformation to {transforms_applied} nodes[/green]"
            )

        onnx.save(model, output_path)

    return output_path


def downgrade_opset(
    onnx_path: str,
    target_opset: int = 11,
    output_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> str:
    """
    Downgrade ONNX opset version for SNPE compatibility.

    Args:
        onnx_path: Path to the input ONNX model
        target_opset: Target opset version (default 11 for SNPE compatibility)
        output_path: Path for the output model (defaults to overwriting input)
        console: Rich console for output

    Returns:
        Path to the transformed model
    """
    import onnx
    from onnx import version_converter

    model = onnx.load(onnx_path)

    if output_path is None:
        output_path = onnx_path

    current_opset = model.opset_import[0].version
    if current_opset <= target_opset:
        if console:
            console.print(
                f"[blue]Model opset {current_opset} is already at or below target {target_opset}[/blue]"
            )
        return output_path

    if console:
        console.print(
            f"[blue]Downgrading opset from {current_opset} to {target_opset}...[/blue]"
        )

    try:
        converted_model = version_converter.convert_version(model, target_opset)
        onnx.save(converted_model, output_path)
        if console:
            console.print(f"[green]Successfully downgraded to opset {target_opset}[/green]")
    except Exception as e:
        if console:
            console.print(
                f"[yellow]Warning: Could not downgrade opset: {e}. "
                "Proceeding with original version.[/yellow]"
            )

    return output_path


def apply_transforms(
    onnx_path: str,
    output_path: Optional[str] = None,
    console: Optional[Console] = None,
) -> str:
    """
    Apply all ONNX transformations for SNPE compatibility.

    Args:
        onnx_path: Path to the input ONNX model
        output_path: Path for the output model (defaults to overwriting input)
        console: Rich console for output

    Returns:
        Path to the transformed model
    """
    if output_path is None:
        output_path = onnx_path

    # Apply GEMM fix
    fix_gemm_transpose(onnx_path, output_path, console)

    # Downgrade opset if needed
    downgrade_opset(output_path, target_opset=11, output_path=output_path, console=console)

    return output_path
