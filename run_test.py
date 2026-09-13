"""
QServe test runner.

Stages:
  m3_appium - connect, launch, dump every screen element so you can build
              real locators instead of guessing coordinates
  m4_login  - scan the QR from the gallery and log in
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

APP_PACKAGE = "com.qart.qserve"
APP_ACTIVITY = "com.qart.qserve.MainActivity"
APPIUM_URL = "http://127.0.0.1:4723"
ARTIFACTS = "artifacts"

_n = 0


def make_driver():
    o = UiAutomator2Options()
    o.platform_name = "Android"
    o.automation_name = "UiAutomator2"
    o.app_package = APP_PACKAGE
    o.app_activity = APP_ACTIVITY
    o.no_reset = True          # already installed + cleared by the workflow
    o.auto_grant_permissions = True
    o.set_capability("appium:newCommandTimeout", 300)
    o.set_capability("appium:appWaitActivity", "*")
    o.set_capability("appium:forceAppLaunch", True)
    return webdriver.Remote(APPIUM_URL, options=o)


def capture(driver, label):
    """Screenshot + accessibility tree. These are your debugger."""
    global _n
    _n += 1
    os.makedirs(ARTIFACTS, exist_ok=True)
    stem = f"{ARTIFACTS}/{_n:02d}_{label}"
    try:
        driver.get_screenshot_as_file(f"{stem}.png")
    except Exception as e:
        print(f"  [capture] screenshot failed: {e}")
    try:
        with open(f"{stem}.xml", "w", encoding="utf-8") as fh:
            fh.write(driver.page_source)
    except Exception as e:
        print(f"  [capture] page_source failed: {e}")
    print(f"  captured {stem}.png / .xml")


def dump_elements(driver, title):
    """Print everything with an identifier. Build locators from this list."""
    print(f"\n---------- {title} ----------")
    found = 0
    try:
        els = driver.find_elements(AppiumBy.XPATH, "//*[@content-desc or @resource-id]")
    except Exception as e:
        print(f"  could not read elements: {e}")
        return
    for el in els:
        try:
            desc = el.get_attribute("content-desc") or ""
            rid = el.get_attribute("resource-id") or ""
            txt = (el.get_attribute("text") or "")[:40]
            cls = (el.get_attribute("class") or "").split(".")[-1]
            if desc or rid:
                found += 1
                print(f"  <{cls:<18} desc={desc!r:<38} id={rid!r:<28} text={txt!r}")
        except Exception:
            continue
    print(f"---------- {found} elements ----------\n")


def tap_any(driver, locators, timeout=8):
    """Click the first locator that works. Returns True on success."""
    for by, val in locators:
        try:
            WebDriverWait(driver, timeout).until(
                EC.element_to_be_clickable((by, val))
            ).click()
            print(f"  tapped via {val}")
            return True
        except Exception:
            continue
    return False


SCAN_QR = [
    (AppiumBy.ACCESSIBILITY_ID, "Scan QR from gallery"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionContains("Scan QR")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textContains("Scan QR")'),
]

LOGIN = [
    (AppiumBy.ACCESSIBILITY_ID, "Login"),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().descriptionMatches("(?i).*log ?in.*")'),
    (AppiumBy.ANDROID_UIAUTOMATOR, 'new UiSelector().textMatches("(?i).*log ?in.*")'),
]


def stage_m3(driver):
    """Prove Appium can see the app, and inventory the login screen."""
    print("[m3] waiting for Flutter + Firebase to initialise")
    time.sleep(12)
    capture(driver, "launch")

    pkg = driver.current_package
    print(f"[m3] foreground package: {pkg}")
    if pkg != APP_PACKAGE:
        raise AssertionError(f"Expected {APP_PACKAGE}, got {pkg}")

    print(f"[m3] screen size: {driver.get_window_size()}")
    dump_elements(driver, "LOGIN SCREEN")
    print("[m3] PASSED")


def stage_m4(driver):
    """Scan the injected QR from the gallery, then log in."""
    print("[m4] waiting for app to settle")
    time.sleep(12)
    capture(driver, "launch")

    print("[m4] tapping 'Scan QR from gallery'")
    if not tap_any(driver, SCAN_QR):
        capture(driver, "no_scan_button")
        dump_elements(driver, "SCREEN WHEN SCAN BUTTON NOT FOUND")
        raise AssertionError("'Scan QR from gallery' button not found")
    time.sleep(4)
    capture(driver, "picker")
    dump_elements(driver, "PHOTO PICKER")

    # The QR is the only image on a fresh emulator, so the first thumbnail
    # is guaranteed to be it. No coordinate guessing needed.
    print("[m4] selecting the QR image")
    thumbs = driver.find_elements(
        AppiumBy.ANDROID_UIAUTOMATOR,
        'new UiSelector().className("android.widget.ImageView").clickable(true)',
    )
    print(f"  found {len(thumbs)} clickable images")
    if not thumbs:
        capture(driver, "no_thumbnail")
        raise AssertionError("No image thumbnail in the picker")
    thumbs[0].click()
    time.sleep(4)
    capture(driver, "after_select")

    print("[m4] waiting to return to the app")
    for _ in range(20):
        if driver.current_package == APP_PACKAGE:
            break
        time.sleep(1)
    time.sleep(3)
    capture(driver, "back_in_app")
    dump_elements(driver, "AFTER QR SCAN")

    print("[m4] tapping Login")
    if not tap_any(driver, LOGIN):
        capture(driver, "no_login_button")
        raise AssertionError("Login button not found after QR scan")
    time.sleep(8)
    capture(driver, "home")
    dump_elements(driver, "HOME SCREEN")
    print("[m4] PASSED")


STAGES = {"m3_appium": stage_m3, "m4_login": stage_m4}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True)
    args = ap.parse_args()

    fn = STAGES.get(args.stage)
    if fn is None:
        print(f"Unknown stage: {args.stage}. Available: {', '.join(STAGES)}")
        return 2

    driver = None
    try:
        print("Connecting to Appium...")
        driver = make_driver()
        print(f"Session: {driver.session_id}")
        fn(driver)
        return 0
    except Exception as e:
        print(f"\n!!! FAILED: {type(e).__name__}: {e}")
        if driver is not None:
            capture(driver, "failure")
        return 1
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
