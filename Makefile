PROJECT_NAME := synapsectl
PROTOC := protoc
PYTHON_GRPC := python -m grpc_tools.protoc
PROTO_DIR := ./synapse-api
PROTO_OUT := ./synapse
PROTOS := $(shell find ${PROTO_DIR} -name '*.proto' | sed 's|${PROTO_DIR}/||')
GRPC_CPP_PLUGIN := $(shell which grpc_cpp_plugin)

.PHONY: all
all: clean generate

.PHONY: clean
clean:
	rm -rf bin ${PROTO_OUT}/api*

.PHONY: generate
generate:
	mkdir -p bin
	mkdir -p ${PROTO_OUT}
	${PROTOC} -I=${PROTO_DIR} --descriptor_set_out=bin/descriptors.binpb ${PROTOS}
	${PROTOC} -I=${PROTO_DIR} --python_out=${PROTO_OUT} --cpp_out=${PROTO_OUT} ${PROTOS}
	${PYTHON_GRPC} -I=${PROTO_DIR} --grpc_python_out=${PROTO_OUT} api/synapse.proto
	${PROTOC} -I=${PROTO_DIR} --plugin=protoc-gen-grpc_cpp=${GRPC_CPP_PLUGIN} --grpc_cpp_out=${PROTO_OUT} api/synapse.proto
	protol --create-package --in-place --python-out ${PROTO_OUT} raw bin/descriptors.binpb

test:
	pytest -v