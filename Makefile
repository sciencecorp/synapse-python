PROJECT_NAME := synapsectl
CMD_PROTOC := python -m grpc_tools.protoc
PROTO_DIR := ./synapse-api
PROTO_OUT := ./synapse

# Detect OS and set commands accordingly
ifeq ($(OS),Windows_NT)
    CMD_RM = if exist "$1" rmdir /s /q "$1"
    CMD_MKDIR = if not exist "$1" mkdir "$1"
    PROTOS := $(shell python -c "import glob; import os; print(' '.join([p.replace(os.sep, '/').replace('$(PROTO_DIR)/', '') for p in glob.glob('$(PROTO_DIR)/**/*.proto', recursive=True)]))")
else
    CMD_RM = rm -rf $(1)
    CMD_MKDIR = mkdir -p $(1)
    PROTOS := $(shell find $(PROTO_DIR) -name '*.proto' | sed 's|$(PROTO_DIR)/||')
endif

.PHONY: all
all: clean generate

.PHONY: clean
clean:
	$(CMD_RM) bin
	$(CMD_RM) $(PROTO_OUT)/api*

.PHONY: generate
generate:
	$(call CMD_MKDIR,bin)
	$(call CMD_MKDIR,$(PROTO_OUT))
	$(CMD_PROTOC) -I=$(PROTO_DIR) --descriptor_set_out=bin/descriptors.binpb $(PROTOS)
	$(CMD_PROTOC) -I=$(PROTO_DIR) --python_out=$(PROTO_OUT) $(PROTOS)
	$(CMD_PROTOC) -I=$(PROTO_DIR) --grpc_python_out=$(PROTO_OUT) api/synapse.proto
	protol --create-package --in-place --python-out $(PROTO_OUT) raw bin/descriptors.binpb

test:
	pytest -v
