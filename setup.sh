#!/bin/bash

# Define variables
PROTOC="python -m grpc_tools.protoc"
PROTO_DIR_SYNAPSE_API="./synapse-api"
PROTO_OUT_SYNAPSE_API="./synapse"

clean() {
    echo "Cleaning up..."
    rm -rf bin "${PROTO_OUT_SYNAPSE_API}/api"*
}

generate_protos() {
    local input_proto_dir="$1"
    local output_proto_dir="$2"
    local service_proto="$3"

    if [ -z "$input_proto_dir" ]; then
        echo "Error: input proto directory is required"
        exit 1
    fi

    if [ -z "$output_proto_dir" ]; then
        echo "Error: output proto directory is required"
        exit 1
    fi

    if [ -z "$service_proto" ]; then
        echo "Error: service proto file is required"
        exit 1
    fi

    echo "Generating protobuf files..."
    echo "- input: ${input_proto_dir}"
    echo "- output: ${output_proto_dir}"
    echo "- service: ${service_proto}"

    mkdir -p bin
    mkdir -p "${output_proto_dir}"
    
    # Store proto files in an array
    PROTOS=($(find "${input_proto_dir}" -name "*.proto" | sed "s|${input_proto_dir}/||"))
    
    # Generate descriptor set
    ${PROTOC} -I="${input_proto_dir}" --descriptor_set_out=bin/descriptors.binpb "${PROTOS[@]}"
    
    # Generate Python files
    ${PROTOC} -I="${input_proto_dir}" --python_out="${output_proto_dir}" "${PROTOS[@]}"
    
    # Generate gRPC Python files
    ${PROTOC} -I="${input_proto_dir}" --grpc_python_out="${output_proto_dir}" "${service_proto}"
    
    # Run protol
    protol --create-package --in-place --python-out "${output_proto_dir}" raw bin/descriptors.binpb
}

generate() {
    generate_protos "${PROTO_DIR_SYNAPSE_API}" "${PROTO_OUT_SYNAPSE_API}" "api/synapse.proto"
}

generate_version() {
    echo "Generating version file..."
    git -C ${PROTO_DIR_SYNAPSE_API} describe --tags --abbrev=0 | sed 's/^v//' > ${PROTO_OUT_SYNAPSE_API}/api/version.txt || echo "0.0.0" > ${PROTO_OUT_SYNAPSE_API}/api/version.txt
}

run_tests() {
    echo "Running tests..."
    pytest -v
}

# Main script logic
case "$1" in
    "clean")
        clean
        ;;
    "generate")
        generate
        generate_version
        ;;
    "test")
        run_tests
        ;;
    "all")
        clean
        generate
        generate_version
        ;;
    *)
        echo "Usage: $0 {clean|generate|test|all}"
        echo "For generate: $0 generate [input_proto_dir] [output_proto_dir] [service_proto]"
        exit 1
        ;;
esac

exit 0
