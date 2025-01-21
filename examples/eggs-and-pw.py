from __future__ import annotations

import pathlib
import os

import AppKit

from twisted.internet.interfaces import IReactorTime
from twisted.internet.defer import Deferred
from twisted.python.failure import Failure

from quickmacapp import mainpoint, Status, answer, quit, getpass

async def eggsPassword() -> None:
    pw = await getpass("please enter your egg password")
    await answer (f"I tricked you, your password is {pw}")


@mainpoint()
def app(reactor: IReactorTime) -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    status = Status("🥚🔒")
    status.menu(
        [
            (
                "About",
                lambda: Deferred.fromCoroutine(
                    answer(
                        "Secure Your Eggs In One Basket",
                    )
                ),
            ),
            (
                "Enter Password for Eggs",
                lambda: Deferred.fromCoroutine(eggsPassword()).addErrback(lambda f: f.printTraceback()),
            ),
            ("Quit", quit),
        ]
    )


if __name__ == "__main__":
    app.runMain()
