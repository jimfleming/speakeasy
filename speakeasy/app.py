"""Speakeasy menu-bar app.

Wraps the listener (speakeasy/listener.py) in a rumps menu-bar item. The HTTP
server runs in a background thread; Kokoro warms asynchronously. Left-click
toggles mute; right-click (or control-click) opens the menu: mute, speak last
again, open config, quit.
"""
import subprocess
import threading

import rumps
from AppKit import (
    NSApp,
    NSEventMaskLeftMouseDown,
    NSEventMaskRightMouseDown,
    NSEventModifierFlagControl,
    NSEventTypeRightMouseDown,
    NSImage,
)
from Foundation import NSObject

from speakeasy import config, listener


def _sf_symbol(name):
    """Load a system SF Symbol as a template NSImage."""
    image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
    image.setTemplate_(True)
    return image


IDLE = _sf_symbol("waveform.circle.fill")
WARMING = _sf_symbol("hourglass.circle.fill")
MUTED = _sf_symbol("waveform.circle")


class _ClickHandler(NSObject):
    """Obj-C target for the status-item button's click action."""

    def onClick_(self, _sender):
        self.app._on_status_click()


class SpeakeasyApp(rumps.App):
    def __init__(self):
        super().__init__("Speakeasy")
        self._set_icon(WARMING)
        self._ready = False
        self._mute = rumps.MenuItem("Mute", callback=self._toggle_mute)
        self.menu = [
            self._mute,
            rumps.MenuItem("Speak last again", callback=self._speak_last),
            None,
            rumps.MenuItem("Open config", callback=self._open_config),
        ]
        threading.Thread(target=listener.serve, daemon=True).start()
        threading.Thread(target=self._warm, daemon=True).start()

    def run(self):
        rumps.events.before_start.register(self._install_clicks)
        super().run()

    def _install_clicks(self):
        button = self._nsapp.nsstatusitem.button()
        self._nsapp.nsstatusitem.setMenu_(None)
        self._click_handler = _ClickHandler.alloc().init()
        self._click_handler.app = self
        button.setTarget_(self._click_handler)
        button.setAction_("onClick:")
        button.sendActionOn_(NSEventMaskLeftMouseDown | NSEventMaskRightMouseDown)

    def _on_status_click(self):
        event = NSApp.currentEvent()
        right = event.type() == NSEventTypeRightMouseDown or bool(
            event.modifierFlags() & NSEventModifierFlagControl
        )
        if right:
            self._open_menu()
        elif self._ready:
            self._toggle_mute(self._mute)

    def _open_menu(self):
        statusitem = self._nsapp.nsstatusitem
        statusitem.setMenu_(self.menu._menu)
        statusitem.button().performClick_(None)
        statusitem.setMenu_(None)

    def _set_icon(self, image):
        self._icon_nsimage = image
        if hasattr(self, "_nsapp"):
            self._nsapp.setStatusBarIcon()

    def _warm(self):
        listener.kokoro.warm()
        self._ready = True
        self._set_icon(MUTED if self._mute.state else IDLE)

    def _toggle_mute(self, sender):
        sender.state = not sender.state
        listener.set_muted(bool(sender.state))
        self._set_icon(MUTED if sender.state else IDLE)

    def _speak_last(self, _):
        threading.Thread(target=listener.say_last, daemon=True).start()

    def _open_config(self, _):
        subprocess.run(["open", str(config.CONFIG_PATH)])


def main():
    SpeakeasyApp().run()


if __name__ == "__main__":
    main()
