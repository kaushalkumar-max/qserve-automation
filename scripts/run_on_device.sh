#!/usr/bin/env bash
# Runs INSIDE the emulator-runner action, after the AVD has booted.
#
# This lives in a file rather than inline in the YAML because the
# emulator-runner action executes each line of an inline script as a
# SEPARATE shell, which breaks if/then/fi, loops and functions.
set -e

STAGE="${STAGE:-m1_emulator}"
PKG="com.qart.qserve"
mkdir -p artifacts
echo "########## STAGE = $STAGE ##########"

echo "########## EMULATOR IS ALIVE ##########"
adb devices
echo "Android: $(adb shell getprop ro.build.version.release)"
echo "API:     $(adb shell getprop ro.build.version.sdk)"
echo "ABI:     $(adb shell getprop ro.product.cpu.abi)"
if adb shell pm list packages | grep -q "com.google.android.gms"; then
  echo "Play Services: YES (google_apis image confirmed)"
else
  echo "Play Services: NO - wrong system image!"
fi

if [ "$STAGE" = "m1_emulator" ]; then
  echo "########## M1 PASSED ##########"
  exit 0
fi

echo "########## INSTALLING APK ##########"
adb install -g -r build/app.apk
# Wipe ObjectBox DB + prefs so runs never contaminate each other.
adb shell pm clear "$PKG"
adb shell dumpsys package "$PKG" | grep versionName | head -1 || true

adb logcat -c

if [ "$STAGE" = "m2_install" ]; then
  echo "########## LAUNCHING APP ##########"
  adb shell monkey -p "$PKG" -c android.intent.category.LAUNCHER 1
  sleep 15
  adb exec-out screencap -p > artifacts/launch.png
  echo "Foreground: $(adb shell dumpsys window | grep -E 'mCurrentFocus' | head -1)"
  adb logcat -d | grep -E "FATAL EXCEPTION|ANR in|E/flutter" \
    > artifacts/crashes.txt || echo "no crashes detected" > artifacts/crashes.txt
  echo "--- crashes.txt ---"
  cat artifacts/crashes.txt
  echo "########## M2 DONE - check launch.png in artifacts ##########"
  exit 0
fi

if [ "$STAGE" = "m4_login" ]; then
  echo "########## INJECTING QR ##########"
  if [ -z "${QSERVE_QR_B64:-}" ]; then
    echo "ERROR: QSERVE_QR_B64 secret is not set." >&2
    exit 1
  fi
  mkdir -p .qr
  echo "$QSERVE_QR_B64" | base64 -d > .qr/qr.png
  adb push .qr/qr.png /sdcard/Pictures/qr.png
  adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE \
    -d file:///sdcard/Pictures/qr.png
  rm -rf .qr
  sleep 2
fi

echo "########## STARTING APPIUM ##########"
appium --log-level error --log artifacts/appium.log &
for i in $(seq 1 40); do
  if curl -sf http://127.0.0.1:4723/status > /dev/null; then
    echo "Appium ready"
    break
  fi
  sleep 1
done

adb shell screenrecord --bit-rate 2000000 --time-limit 180 /sdcard/run.mp4 &
REC=$!

set +e
python tests/run_test.py --stage "$STAGE"
CODE=$?
set -e

kill $REC 2>/dev/null || true
sleep 3
adb pull /sdcard/run.mp4 artifacts/run.mp4 || echo "no video captured"
adb logcat -d | grep -E "FATAL EXCEPTION|ANR in|E/flutter" \
  > artifacts/crashes.txt || echo "no crashes detected" > artifacts/crashes.txt
echo "--- crashes.txt ---"
cat artifacts/crashes.txt

exit $CODE
