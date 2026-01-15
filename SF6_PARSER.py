import os
import sys
import threading
from datetime import datetime
from typing import Dict, Set, List
""" 
    ---READ THIS---
    Enable reWASD
    works with python 3.14
    pip install pygame-ce           (2.5.6)
    pip install pygame-ce keyboard  (0.13.5)
    pip install setuptools          (80.9.0)
"""
# Global hotkeys (F1, ESC) even when unfocused
import keyboard  # pip install keyboard
import pygame

# ---------------- Configuration ---------------- #
FPS = 60
DEBUG = False  # set True to print raw events/mappings

# Button index to human-friendly name (common DS4 over SDL on Windows)
BUTTON_MAP: Dict[int, str] = {
    0: "LK()",
    1: "MK()",
    2: "LP()",
    3: "MP()",
    4: "L1",
    5: "HP()",
    8: "Share",
    9: "Options",
    10: "L3",
    11: "R3",
    12: "PS",
    13: "Touchpad",
    # Some drivers also expose L2/R2 as buttons (6,7); we'll primarily treat them as axes below
}

# Trigger axes (analog). We'll treat them as buttons using a threshold.
AXIS_MAP = {
    "DRIVE_RUSH()": 4,
    "HK()": 5,
}
TRIGGER_THRESHOLD = 0.5  # consider pressed if axis value >= 0.5 (adjust if needed)

# D-Pad is typically a HAT (hat index 0). We'll map to directional names.
HAT_INDEX = 0
DPAD_NAMES = {
    (0, 1): {"UP()"},
    (0, -1): {"DOWN()"},
    (-1, 0): {"LEFT()"},
    (1, 0): {"RIGHT()"},
    (-1, 1): {"UP()", "LEFT()"},
    (1, 1): {"UP()", "RIGHT()"},
    (-1, -1): {"DOWN()", "LEFT()"},
    (1, -1): {"DOWN()", "RIGHT()"},
    (0, 0): set(),
}


class DS4ParserBG:
    def __init__(self):
        # Hint: allow SDL joystick processing even when window isn't focused
        # (Polling works either way, but this doesn't hurt.)
        os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

        pygame.init()
        pygame.joystick.init()

        if pygame.joystick.get_count() == 0:
            print("No joystick detected. Connect your DS4 via Bluetooth and try again.")
            sys.exit(1)

        self.joy = pygame.joystick.Joystick(0)
        self.joy.init()
        print(f"Using controller: {self.joy.get_name()}")

        # Create a tiny hidden window so pygame has a video context, but it won’t steal focus.
        # HIDDEN flag exists in pygame 2.x; fall back gracefully if not available.
        flags = 0
        if hasattr(pygame, "HIDDEN"):
            flags |= pygame.HIDDEN
        if hasattr(pygame, "NOFRAME"):
            flags |= pygame.NOFRAME
        try:
            pygame.display.set_mode((1, 1), flags)
        except Exception:
            # Fallback: minimal window
            pygame.display.set_mode((1, 1))

        self.clock = pygame.time.Clock()

        # Recording state
        self.is_recording: bool = False
        self.lines: List[str] = []
        self.frames_since_last_event: int = 0
        self.downtime_only: bool = True  # True iff no buttons were held since last event

        # Input states to detect transitions
        self.pressed_buttons: Set[str] = set()  # names currently held (excluding dpad/triggers)
        self.prev_hat_dirs: Set[str] = set()
        self.prev_trigger_pressed: Set[str] = set()

        # Control
        self.running = True

        # Start global hotkeys on a daemon thread
        t = threading.Thread(target=self._global_hotkeys, daemon=True)
        t.start()

    # ------------------- Global Hotkeys ------------------- #
    def _global_hotkeys(self):
        # Toggle recording with F1 anywhere
        keyboard.add_hotkey("f1", self.toggle_recording)
        # Quit with Esc anywhere
        keyboard.add_hotkey("esc", self.stop_program)
        keyboard.wait()  # keep the listener thread alive

    def toggle_recording(self):
        if not self.is_recording:
            print("Recording started.")
            self.is_recording = True
            self.lines.clear()
            self.frames_since_last_event = 0
            self.downtime_only = True
        else:
            print("Recording stopped. Saving file…")
            self.is_recording = False
            self.save_output()

    def stop_program(self):
        print("Exiting…")
        # If currently recording, save before quitting
        if self.is_recording:
            self.is_recording = False
            self.save_output()
        self.running = False

    # ------------------- Emit Helpers ------------------- #
    def emit_sleep_if_needed(self):
        n = self.frames_since_last_event
        if n <= 0:
            return
        if self.downtime_only:
            n = min(n, 99)  # cap downtime at 99
        self.lines.append(f"sleep({n})")
        if DEBUG:
            print(self.lines[-1])
        self.frames_since_last_event = 0
        self.downtime_only = True  # reset

    def emit_press(self, name: str):
        self.emit_sleep_if_needed()
        self.lines.append(f"p{name}")
        if DEBUG:
            print(self.lines[-1])
        self.frames_since_last_event = 0  # reset; next frames will decide downtime-only

    def emit_release(self, name: str):
        self.emit_sleep_if_needed()
        self.lines.append(f"r{name}")
        if DEBUG:
            print(self.lines[-1])
        self.frames_since_last_event = 0

    # ------------------- Polling Helpers ------------------- #
    def current_dpad_dirs(self) -> Set[str]:
        try:
            x, y = self.joy.get_hat(HAT_INDEX)
        except Exception:
            return set()
        return DPAD_NAMES.get((x, y), set())

    def current_trigger_pressed(self) -> Set[str]:
        pressed = set()
        for name, axis_idx in AXIS_MAP.items():
            try:
                val = self.joy.get_axis(axis_idx)
            except Exception:
                continue
            # Normalize to [0..1] if needed (some drivers use -1..1)
            if val < 0.0:
                val = (val + 1.0)
            if val >= TRIGGER_THRESHOLD:
                pressed.add(name)
        return pressed

    def poll_buttons_pressed(self) -> Set[str]:
        """Return the set of button names currently held (excluding dpad & triggers)."""
        held = set()
        for idx, name in BUTTON_MAP.items():
            try:
                if self.joy.get_button(idx):
                    held.add(name)
            except Exception:
                continue
        return held

    # ------------------- Save ------------------- #
    def save_output(self):
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        fname = f"ds4_log_{ts}.txt"
        with open(fname, "w", encoding="utf-8") as f:
            for line in self.lines:
                f.write(line + "\n")
        print(f"Saved: {fname}")

    # ------------------- Frame Update ------------------- #
    def update(self):
        # Keep SDL internal state fresh (important when not using event loop)
        pygame.event.pump()

        # Read current states
        button_held = self.poll_buttons_pressed()
        hat_dirs = self.current_dpad_dirs()
        trig_held = self.current_trigger_pressed()

        # Build a unified set of held names for downtime tracking
        held_names = set(button_held) | set(hat_dirs) | set(trig_held)

        # Detect transitions for dpad
        new_hat_presses = hat_dirs - self.prev_hat_dirs
        hat_releases = self.prev_hat_dirs - hat_dirs

        # Detect transitions for triggers
        new_trig_presses = trig_held - self.prev_trigger_pressed
        trig_releases = self.prev_trigger_pressed - trig_held

        # Detect transitions for normal buttons
        prev_buttons_only = self.pressed_buttons - self.prev_hat_dirs - self.prev_trigger_pressed
        curr_buttons_only = button_held
        new_btn_presses = curr_buttons_only - prev_buttons_only
        btn_releases = prev_buttons_only - curr_buttons_only

        if self.is_recording:
            # Update downtime flag based on whether any input is held during this frame
            if held_names:
                self.downtime_only = False

            # Emit presses (buttons, dpad, triggers)
            for name in sorted(new_btn_presses):
                self.emit_press(name)
            for name in sorted(new_hat_presses):
                self.emit_press(name)
            for name in sorted(new_trig_presses):
                self.emit_press(name)

            # Emit releases
            for name in sorted(btn_releases):
                self.emit_release(name)
            for name in sorted(hat_releases):
                self.emit_release(name)
            for name in sorted(trig_releases):
                self.emit_release(name)

            # Advance frame counter AFTER processing events
            self.frames_since_last_event += 1

        # Update previous states for next frame
        self.pressed_buttons = set(button_held)
        self.prev_hat_dirs = set(hat_dirs)
        self.prev_trigger_pressed = set(trig_held)

    # ------------------- Main Loop ------------------- #
    def run(self):
        print("Global hotkeys: F1 = start/stop recording, Esc = quit (works while unfocused).")
        while self.running:
            self.update()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == "__main__":
    DS4ParserBG().run()
