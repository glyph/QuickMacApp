from __future__ import annotations

import os
import pathlib

import AppKit
from quickmacapp import Status, mainpoint
from twisted.internet.interfaces import IReactorTime


@mainpoint()
def app(reactor: IReactorTime) -> None:
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyRegular
    )

    def check_sun():
        print("Sun is still not destroyed")
    def destroy_sun():
        print("Sun destruction capabalities still not deployed")

    status = Status("☀️ 💣")
    status.menu([("Check sun", check_sun), ("Destroy sun", destroy_sun)])

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
