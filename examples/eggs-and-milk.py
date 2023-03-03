from __future__ import annotations

import pathlib
import os

import AppKit

from twisted.internet.interfaces import IReactorTime
from twisted.internet.defer import Deferred
from twisted.python.failure import Failure

from quickmacapp import mainpoint, Status, ask, choose, answer

resultTemplate = """
You need to go to the store to get more eggs in {eggDays} days
You need to go to the store to get more milk in {milkDays} days
You will need to bring around ${eggPrice} to get the same amount of eggs
You will need to bring around ${milkPrice} to get the same amount of milk
Thank you
"""

# Prices from reference implementation, possibly accurate circa 2002
eggUnitPrice = 0.09083
milkOuncePrice = 0.05


def alwaysFloat(value: str | None) -> float:
    try:
        return float(value or "nan")
    except:
        return float("nan")


async def eggsAndMilkMinder() -> None:
    eggCount = alwaysFloat(await ask("Enter the number of eggs you have"))
    eatEggCount = alwaysFloat(await ask("Enter the number of eggs you eat per day"))
    milkCount = alwaysFloat(await ask("Enter the number of ounces of milk you have"))
    drinkMilkCount = alwaysFloat(
        await ask("Enter in the amount of milk you drink each day in ounces")
    )
    await answer(
        resultTemplate.format(
            eggDays=(eggCount / eatEggCount),
            milkDays=(milkCount / drinkMilkCount),
            eggPrice=eggCount * eggUnitPrice,
            milkPrice=milkCount * milkOuncePrice,
        )
    )
    hashBrowns = await choose(
        [(True, "y"), (False, "n")],
        "Would you like to also make some delicious hashbrowns?",
    )
    await answer(
        (
            "Then you will need to get some potatoes and grate them,"
            " also some onions and cook it all so it's delicious"
        )
        if hashBrowns
        else (
            "Suit yourself, but hashbrowns are delicious,"
            " you should definitely have them sometime"
        ),
    )


@mainpoint()
def app(reactor: IReactorTime) -> None:
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    status = Status("🥚🥛")
    status.menu(
        [
            (
                "About",
                lambda: Deferred.fromCoroutine(
                    answer(
                        "Eggs And Milk Minder 1.0c",
                        "With apologies to Roast Beef Kazenzakis",
                    )
                ),
            ),
            (
                "Calculate Eggs And Milk",
                lambda: Deferred.fromCoroutine(eggsAndMilkMinder()),
            ),
            ("Quit", lambda: app.terminate_(None)),
        ]
    )


if __name__ == "__main__":
    app.runMain()
