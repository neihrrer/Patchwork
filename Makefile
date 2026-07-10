.PHONY: all setup build run clean install uninstall dev

BUILD_DIR = build

all: build

setup:
	meson setup $(BUILD_DIR)

build:
	meson compile -C $(BUILD_DIR)

run: build
	./run.sh

clean:
	rm -rf $(BUILD_DIR)
	rm -rf __pycache__
	find . -name '*.pyc' -delete

install:
	sudo meson install -C $(BUILD_DIR)

uninstall:
	sudo ninja -C $(BUILD_DIR) uninstall 2>/dev/null || true

dev:
	./run.sh

rebuild: clean setup build
