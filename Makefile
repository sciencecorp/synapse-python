PROJECT_NAME := synapsectl
PROTOC := python -m grpc_tools.protoc
PROTO_DIR := ./synapse-api
PROTO_OUT := ./synapse
PROTOS := $(shell find ${PROTO_DIR} -name '*.proto' | sed 's|${PROTO_DIR}/||')

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
	${PROTOC} -I=${PROTO_DIR} --python_out=${PROTO_OUT} ${PROTOS}
	${PROTOC} -I=${PROTO_DIR} --grpc_python_out=${PROTO_OUT} api/synapse.proto
	protol --create-package --in-place --python-out ${PROTO_OUT} raw bin/descriptors.binpb

test:
	pytest -v