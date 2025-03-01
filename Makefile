.PHONY: all
all:
	./setup.sh all

.PHONY: clean
clean:
	./setup.sh clean

.PHONY: generate
generate:
	./setup.sh generate

.PHONY: test
test:
	./setup.sh test
	