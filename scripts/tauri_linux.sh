#!/bin/sh
# Make a rustup installation visible to Tauri without changing the user's shell.
set -eu

if ! command -v cargo >/dev/null 2>&1; then
    cargo_home=${CARGO_HOME:-${HOME:-}/.cargo}
    if [ -n "$cargo_home" ] && [ -x "$cargo_home/bin/cargo" ]; then
        PATH="$cargo_home/bin:$PATH"
        export PATH
    else
        printf '%s\n' 'Cargo was not found. Install the Linux Rust toolchain or add its bin directory to PATH.' >&2
        exit 1
    fi
fi

exec tauri "$@"
