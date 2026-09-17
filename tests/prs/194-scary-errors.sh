#!/usr/bin/env bash
set -uo pipefail

DEVICE="127.0.0.1"
SYNAPSECTL_BIN="${SYNAPSECTL:-}"

while (($#)); do
    case "$1" in
        --device)
            [[ $# -ge 2 ]] || { echo "--device requires an IP address" >&2; exit 2; }
            DEVICE="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--device <ip>]"
            echo "Set SYNAPSECTL=/path/to/synapsectl to override executable discovery."
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if [[ -z "$SYNAPSECTL_BIN" ]]; then
    SYNVENV_CTL="$HOME/Documents/venvs/synapse-python/bin/synapsectl"
    if [[ -x "$SYNVENV_CTL" ]]; then
        SYNAPSECTL_BIN="$SYNVENV_CTL"
    else
        SYNAPSECTL_BIN="$(command -v synapsectl || true)"
    fi
fi

if [[ -z "$SYNAPSECTL_BIN" || ! -x "$SYNAPSECTL_BIN" ]]; then
    echo "synapsectl was not found; activate synvenv or set SYNAPSECTL." >&2
    exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
touch "$TMP_DIR/not-json.txt"
mkdir "$TMP_DIR/empty-app" "$TMP_DIR/empty-peripheral" "$TMP_DIR/gateware-cwd"

PASS=0
FAIL=0

run_case() {
    local label="$1"
    local kind="$2"
    shift 2
    local output status

    printf '\n=== %s ===\n' "$label"
    printf 'Command:'
    printf ' %q' "$SYNAPSECTL_BIN" "$@"
    printf '\n'

    output="$(timeout 15 "$SYNAPSECTL_BIN" "$@" 2>&1)"
    status=$?
    printf '%s\n' "$output"
    printf '[exit %d]\n' "$status"

    if grep -Eq 'Uncaught|_MultiThreadedRendezvous|debug_error_string|UNKNOWN:Error received from peer' <<<"$output"; then
        echo "FAIL: raw/internal exception details were displayed"
        FAIL=$((FAIL + 1))
        return
    fi

    if [[ "$kind" == "semantic" ]] && grep -Eq '^usage:' <<<"$output"; then
        echo "FAIL: semantic error printed usage"
        FAIL=$((FAIL + 1))
        return
    fi

    if [[ "$kind" == "usage" ]] && ! grep -Eq '^usage:' <<<"$output"; then
        echo "FAIL: usage error did not print usage"
        FAIL=$((FAIL + 1))
        return
    fi

    if [[ -z "$output" ]]; then
        echo "FAIL: command produced no message to inspect"
        FAIL=$((FAIL + 1))
        return
    fi

    echo "PASS"
    PASS=$((PASS + 1))
}

rpc() {
    run_case "$1" semantic --uri "$DEVICE" "${@:2}"
}

run_case "discover: unknown option" usage discover --definitely-invalid
rpc "info: device RPC failure" info
run_case "query: missing query file" semantic query "$TMP_DIR/missing.json"
run_case "start: invalid configuration type" semantic start "$TMP_DIR/not-json.txt"
run_case "stop: extra argument" usage stop app-one app-two
run_case "configure: invalid configuration type" semantic configure "$TMP_DIR/not-json.txt"
run_case "logs: invalid timestamp" semantic logs --start-time not-a-timestamp
run_case "read: missing configuration" semantic read "$TMP_DIR/missing.json"
run_case "plot: missing HDF5 file" semantic plot --data "$TMP_DIR/missing.h5"

run_case "file ls: unknown option" usage file ls --definitely-invalid
run_case "file get: missing remote path" usage file get
run_case "file rm: missing remote path" usage file rm
rpc "taps list: device RPC failure" taps list
rpc "taps stream: unavailable tap" taps stream __missing_tap__

run_case "apps build: missing manifest" semantic apps build "$TMP_DIR/empty-app"
run_case "apps deploy: missing package" semantic apps deploy --package "$TMP_DIR/missing.deb"
rpc "apps list: device RPC failure" apps list

run_case "peripherals build driver: missing manifest" semantic peripherals build driver "$TMP_DIR/empty-peripheral"
run_case "peripherals build gateware: missing manifest" semantic peripherals build gateware "$TMP_DIR/empty-peripheral"
run_case "peripherals build both: missing manifest" semantic peripherals build both "$TMP_DIR/empty-peripheral"
run_case "peripherals deploy driver: missing package" semantic peripherals deploy driver --package "$TMP_DIR/missing.deb"
run_case "peripherals deploy gateware: missing package" semantic peripherals deploy gateware --package "$TMP_DIR/missing.deb"
run_case "peripherals deploy both: missing package" semantic peripherals deploy both --package "$TMP_DIR/missing.deb"
pushd "$TMP_DIR/gateware-cwd" >/dev/null
run_case "peripherals gateware: missing Dockerfile" semantic peripherals gateware doctor
popd >/dev/null

rpc "settings get: device RPC failure" settings get
run_case "settings set: missing value" usage settings set __missing_key__
run_case "deploy-model: missing model" semantic deploy-model "$TMP_DIR/missing.onnx"

printf '\n=== Summary ===\n'
printf '%d passed, %d failed\n' "$PASS" "$FAIL"
((FAIL == 0))
