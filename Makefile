PROJECT_NAME := synapsectl
PROTOC := python -m grpc_tools.protoc
PROTO_DIR := ./synapse-api
PROTO_OUT := ./synapse/api
PROTOS := $(shell find ${PROTO_DIR} -name '*.proto' | sed 's|${PROTO_DIR}/||')
ZMQ_PREFIX := $(shell pwd)/external/zmq

.PHONY: all
all: clean generate

.PHONY: clean
clean:
	rm -rf bin ${PROTO_OUT}

.PHONY: generate
generate:
	mkdir -p bin
	mkdir -p ${PROTO_OUT}
	${PROTOC} -I=${PROTO_DIR} --descriptor_set_out=bin/descriptors.binpb ${PROTOS}
	${PROTOC} -I=${PROTO_DIR} --python_out=${PROTO_OUT} ${PROTOS}
	${PROTOC} -I=${PROTO_DIR} --grpc_python_out=${PROTO_OUT} api/synapse.proto
	protol --create-package --in-place --python-out ${PROTO_OUT} raw bin/descriptors.binpb

.PHONY: install-dependencies
install-dependencies:
	DYLD_LIBRARY_PATH=${ZMQ_PREFIX} \
		ZMQ_PREFIX=${ZMQ_PREFIX} \
		ZMQ_DRAFT_API=1 \
		./scripts/install-zeromq.sh && \
		pip install -v pyzmq --no-binary pyzmq --pre pyzmq --no-cache-dir && \
		pip install -r requirements.txt