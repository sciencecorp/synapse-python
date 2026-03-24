#!/bin/bash
# Idempotent setup script for QCS6490 target device (scifi@10.40.63.143)
# Deploys QNN SDK libraries, BSP libc++, and configures QNN HTP runtime
#
# Usage: ./scripts/setup-target-device.sh [--sdk-version v2.34|v2.42] [SNPE_ROOT]
# Defaults: --sdk-version v2.42
#
# Examples:
#   ./scripts/setup-target-device.sh                      # v2.42 (default)
#   ./scripts/setup-target-device.sh --sdk-version v2.34  # full v2.34 stack
#   ./scripts/setup-target-device.sh /path/to/custom/sdk  # custom SDK path
#
# Prerequisites:
#   - sshpass installed on host
#   - Device accessible at DEVICE_HOST
#   - BSP repo at BSP_ROOT (for Hexagon libc++)

set -euo pipefail

# --- Parse arguments ---
SDK_VERSION="v2.42"
SNPE_ROOT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --sdk-version)
            SDK_VERSION="$2"
            shift 2
            ;;
        --sdk-version=*)
            SDK_VERSION="${1#*=}"
            shift
            ;;
        *)
            SNPE_ROOT="$1"
            shift
            ;;
    esac
done

# --- Resolve SDK path from version if not explicitly provided ---
if [ -z "$SNPE_ROOT" ]; then
    case "$SDK_VERSION" in
        v2.42)
            SNPE_ROOT="/home/calvinl/v2.42.0.251225/qairt/2.42.0.251225"
            ;;
        v2.34)
            SNPE_ROOT="/opt/qcom/aistack/qairt/2.34.0.250424"
            ;;
        *)
            echo "ERROR: Unknown SDK version '$SDK_VERSION'. Supported: v2.34, v2.42"
            exit 1
            ;;
    esac
fi

echo "=== Using SDK version: $SDK_VERSION ==="
echo "    SNPE_ROOT: $SNPE_ROOT"

DEVICE_HOST="${DEVICE_HOST:-scifi@10.40.63.143}"
DEVICE_PASS="${DEVICE_PASS:-synapse}"
ROOT_PASS="${ROOT_PASS:-oelinux123}"
BSP_ROOT="${BSP_ROOT:-/home/calvinl/Documents/repos/qcs6490-ubun-1-0_amss_standard_oem}"
SDK_LIB="${SNPE_ROOT}/lib/aarch64-ubuntu-gcc9.4"
SDK_HEX="${SNPE_ROOT}/lib/hexagon-v68/unsigned"
SDK_BIN="${SNPE_ROOT}/bin/aarch64-ubuntu-gcc9.4"
BSP_CDSP="${BSP_ROOT}/cdsp_proc/build/ms/dynamic_modules/kodiak.cdsp.prod"

# Validate SDK paths exist
for dir in "$SDK_LIB" "$SDK_HEX" "$SDK_BIN"; do
    if [ ! -d "$dir" ]; then
        echo "ERROR: SDK directory not found: $dir"
        exit 1
    fi
done

if [ ! -d "$BSP_CDSP" ]; then
    echo "ERROR: BSP CDSP path not found: $BSP_CDSP"
    echo "  Hexagon libc++ from the BSP is REQUIRED for QNN HTP skel loading."
    echo "  Set BSP_ROOT to the qcs6490-ubun-1-0_amss_standard_oem directory."
    exit 1
fi

echo "=== Staging libraries ==="
STAGING=$(mktemp -d)
trap "rm -rf $STAGING" EXIT

mkdir -p "$STAGING/usr_lib" "$STAGING/adsp" "$STAGING/bin"

# Core QNN/SNPE libraries for /usr/lib/
# Copy all QNN/SNPE/calculator libs from the SDK — covers both v2.34 and v2.42
for lib in "$SDK_LIB"/libQnn*.so "$SDK_LIB"/libSnpe*.so "$SDK_LIB"/libSNPE.so "$SDK_LIB"/libcalculator.so; do
    [ -f "$lib" ] && cp "$lib" "$STAGING/usr_lib/"
done

# Hexagon v68 skel libraries for /usr/lib/rfsa/adsp/
for f in "$SDK_HEX"/*.so; do
    cp "$f" "$STAGING/adsp/"
done

# Hexagon libc++ from BSP (CRITICAL: must match the device's fastrpc_shell)
# The QAIRT SDK does NOT ship these; they come from the device BSP.
# Without these, the QNN HTP skel fails to load with error 0x80000406.
cp "$BSP_CDSP/libc++.so.1" "$STAGING/adsp/"
cp "$BSP_CDSP/libc++abi.so.1" "$STAGING/adsp/"
echo "Staged BSP libc++ for Hexagon DSP"

# Useful debug binaries
for bin in qnn-net-run qnn-platform-validator; do
    if [ -f "$SDK_BIN/$bin" ]; then
        cp "$SDK_BIN/$bin" "$STAGING/bin/"
    fi
done

# Write device-side setup script (heredoc with single-quoted delimiter prevents local expansion)
cat > "$STAGING/apply.sh" <<'APPLY_EOF'
#!/bin/bash
set -e

# --- Remove ALL existing QNN/SNPE libs to prevent version mixing ---
rm -f /usr/lib/libQnn*.so /usr/lib/libSnpe*.so /usr/lib/libSNPE*.so
rm -f /usr/lib/libcalculator.so
rm -f /usr/lib/rfsa/adsp/libQnn*.so /usr/lib/rfsa/adsp/libSnpe*.so
rm -f /usr/lib/rfsa/adsp/libCalculator_skel.so

# --- Install QNN/SNPE libraries to /usr/lib/ ---
cp /tmp/sdk-staging/usr_lib/*.so /usr/lib/

# --- Install hexagon-v68 skel + BSP libc++ to /usr/lib/rfsa/adsp/ ---
cp /tmp/sdk-staging/adsp/*.so /usr/lib/rfsa/adsp/

# --- Install debug binaries ---
cp /tmp/sdk-staging/bin/* /usr/local/bin/ 2>/dev/null || true
chmod +x /usr/local/bin/qnn-* 2>/dev/null || true

# --- Set ADSP_LIBRARY_PATH in /etc/environment ---
if ! grep -q ADSP_LIBRARY_PATH /etc/environment 2>/dev/null; then
    echo "ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp" >> /etc/environment
fi

# --- Set ADSP_LIBRARY_PATH in cdsprpcd service ---
if ! grep -q ADSP_LIBRARY_PATH /lib/systemd/system/cdsprpcd.service 2>/dev/null; then
    sed -i "/\[Service\]/a Environment=ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp" /lib/systemd/system/cdsprpcd.service
    systemctl daemon-reload
fi
# Always restart cdsprpcd to pick up env var
systemctl restart cdsprpcd
sleep 1

# --- Update linker cache ---
ldconfig

# --- Verify ---
echo ""
echo "=== Verification ==="
echo "QNN libs in /usr/lib/:"
ls /usr/lib/libQnn*.so /usr/lib/libSNPE.so 2>/dev/null | xargs -I{} basename {}
echo ""
echo "Skel + libc++ in /usr/lib/rfsa/adsp/:"
ls /usr/lib/rfsa/adsp/libQnn*.so /usr/lib/rfsa/adsp/libc++*.so* 2>/dev/null | xargs -I{} basename {}
echo ""
echo "ADSP_LIBRARY_PATH in cdsprpcd:"
CDSP_PID=$(pgrep cdsprpcd | head -1)
if [ -n "$CDSP_PID" ]; then
    cat /proc/"$CDSP_PID"/environ | tr "\0" "\n" | grep ADSP || echo "(not set)"
else
    echo "(cdsprpcd not running)"
fi
echo ""
echo "Calculator test:"
export ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp
export LD_LIBRARY_PATH=/usr/lib
/usr/local/bin/qnn-platform-validator --backend dsp --testBackend 2>&1 | grep -E "Unit Test|supported"
APPLY_EOF

echo "=== Uploading to device ==="
sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no "$DEVICE_HOST" "rm -rf /tmp/sdk-staging && mkdir -p /tmp/sdk-staging"
sshpass -p "$DEVICE_PASS" scp -o StrictHostKeyChecking=no -r "$STAGING/usr_lib" "$STAGING/adsp" "$STAGING/bin" "$STAGING/apply.sh" "$DEVICE_HOST:/tmp/sdk-staging/"

echo "=== Applying on device as root ==="
sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no "$DEVICE_HOST" "echo '$ROOT_PASS' | su -c 'bash /tmp/sdk-staging/apply.sh' 2>&1"

echo ""
echo "=== Device setup complete (SDK: $SDK_VERSION) ==="
echo ""
echo "To run on device:"
echo "  export ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp"
echo "  export LD_LIBRARY_PATH=/usr/lib:/opt/scifi/lib"
echo "  ./synapse-example-app"
