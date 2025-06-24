from __future__ import annotations

import os
import pathlib

import AppKit
from quickmacapp import Status, mainpoint, ItemState
from twisted.internet.interfaces import IReactorTime


@mainpoint()
def app(reactor: IReactorTime) -> None:
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyRegular
    )

    powered_up: bool = False
    destroy_state = ItemState(enabled=False, key="")

    def power_up():
        nonlocal powered_up
        powered_up = not powered_up
        destroy_state.enabled = powered_up
        print(f"Powering {'up' if powered_up else 'down'} weapons")
        return ItemState(checked=powered_up)

    def destroy_sun():
        print("Sun destruction weapons still insufficiently powerful")

    status = Status("☀️ 💣")
    status.menu(
        [("Power Up Weapons", power_up), ("Destroy Sun", destroy_sun, destroy_state)]
    )

    nib_file = pathlib.Path(__file__).parent / "MainMenu.nib"
    nib_data = AppKit.NSData.dataWithContentsOfFile_(os.fspath(nib_file))
    AppKit.NSNib.alloc().initWithNibData_bundle_(
        nib_data, None
    ).instantiateWithOwner_topLevelObjects_(None, None)

    # When I'm no longer bootstrapping the application I'll want to *not*
    # unconditionally activate here, just have normal launch behavior.
    AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)


if __name__ == "__main__":
    app.runMain()
