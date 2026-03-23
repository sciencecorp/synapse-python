#!/bin/bash
# Idempotent setup script for QCS6490 target device (scifi@10.40.63.143)
# Deploys v2.42 SDK libraries and configures QNN HTP runtime
#
# Usage: ./scripts/setup-target-device.sh [SNPE_ROOT]
# Defaults: SNPE_ROOT=/home/calvinl/v2.42.0.251225/qairt/2.42.0.251225

set -euo pipefail

DEVICE_HOST="${DEVICE_HOST:-scifi@10.40.63.143}"
DEVICE_PASS="${DEVICE_PASS:-synapse}"
ROOT_PASS="${ROOT_PASS:-oelinux123}"
SNPE_ROOT="${1:-/home/calvinl/v2.42.0.251225/qairt/2.42.0.251225}"
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
    echo "WARNING: BSP CDSP path not found: $BSP_CDSP"
    echo "  libc++ for Hexagon DSP will not be deployed."
    echo "  Set BSP_ROOT to the qcs6490 BSP directory."
fi

echo "=== Staging libraries ==="
STAGING=$(mktemp -d)
trap "rm -rf $STAGING" EXIT

mkdir -p "$STAGING/usr_lib" "$STAGING/adsp" "$STAGING/bin"

# Core QNN/SNPE libraries for /usr/lib/
for lib in libQnnCpu.so libQnnGpu.so libQnnHtp.so libQnnHtpPrepare.so \
           libQnnHtpV68Stub.so libQnnHtpV68CalculatorStub.so \
           libQnnSystem.so libSNPE.so libcalculator.so; do
    if [ -f "$SDK_LIB/$lib" ]; then
        cp "$SDK_LIB/$lib" "$STAGING/usr_lib/"
    fi
done

# Hexagon v68 skel libraries for /usr/lib/rfsa/adsp/
for f in "$SDK_HEX"/*.so; do
    cp "$f" "$STAGING/adsp/"
done

# Hexagon libc++ from BSP (CRITICAL: must match the device's fastrpc_shell)
# The QAIRT SDK does not ship these; they come from the device BSP
if [ -d "$BSP_CDSP" ]; then
    cp "$BSP_CDSP/libc++.so.1" "$STAGING/adsp/"
    cp "$BSP_CDSP/libc++abi.so.1" "$STAGING/adsp/"
    echo "Staged BSP libc++ for Hexagon DSP"
fi

# Useful debug binaries
for bin in qnn-net-run qnn-platform-validator; do
    if [ -f "$SDK_BIN/$bin" ]; then
        cp "$SDK_BIN/$bin" "$STAGING/bin/"
    fi
done

echo "=== Uploading to device ==="
sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no "$DEVICE_HOST" "rm -rf /tmp/sdk-staging && mkdir -p /tmp/sdk-staging"
sshpass -p "$DEVICE_PASS" scp -o StrictHostKeyChecking=no -r "$STAGING/usr_lib" "$STAGING/adsp" "$STAGING/bin" "$DEVICE_HOST:/tmp/sdk-staging/"

echo "=== Applying on device as root ==="
sshpass -p "$DEVICE_PASS" ssh -o StrictHostKeyChecking=no "$DEVICE_HOST" "echo '$ROOT_PASS' | su -c '
set -e

# --- Install QNN/SNPE libraries to /usr/lib/ ---
# Remove stale artifacts from other SDK versions
rm -f /usr/lib/libQnnHtpV73*.so /usr/lib/libQnnHtpV69*.so
rm -f /usr/lib/libSnpeHtpV73*.so /usr/lib/libSnpeHtpV69*.so
rm -f /usr/lib/libSNPE_gcc11.so
rm -f /usr/lib/libQnnDsp.so /usr/lib/libQnnDspV66Stub.so
rm -f /usr/lib/libSnpeHtpPrepare.so /usr/lib/libSnpeHtpV68Stub.so

cp /tmp/sdk-staging/usr_lib/*.so /usr/lib/

# --- Install hexagon-v68 skel libraries ---
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
    systemctl restart cdsprpcd
fi

# --- Update linker cache ---
ldconfig

echo "=== Setup complete ==="
echo "QNN libs in /usr/lib/:"
ls /usr/lib/libQnn*.so /usr/lib/libSNPE.so 2>/dev/null | xargs -I{} basename {}
echo "Skel libs in /usr/lib/rfsa/adsp/:"
ls /usr/lib/rfsa/adsp/libQnn*.so 2>/dev/null | xargs -I{} basename {}
echo "ADSP_LIBRARY_PATH in cdsprpcd:"
CDSP_PID=\$(pgrep cdsprpcd | head -1)
if [ -n "\$CDSP_PID" ]; then cat /proc/\$CDSP_PID/environ | tr "\\0" "\\n" | grep ADSP; else echo "(not running)"; fi
' 2>&1"

echo ""
echo "=== Device setup complete ==="
echo "To test on device:"
echo "  export ADSP_LIBRARY_PATH=/usr/lib/rfsa/adsp"
echo "  export LD_LIBRARY_PATH=/usr/lib:/opt/scifi/lib"
echo "  qnn-platform-validator --backend dsp --testBackend"
echo "  ./synapse-example-app"
