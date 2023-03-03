from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Iterable, Iterator, TypeVar

from AppKit import (
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSAlert,
    NSApp,
    NSNotificationCenter,
)
from Foundation import (
    NSCalendar,
    NSCalendarUnitDay,
    NSCalendarUnitHour,
    NSCalendarUnitMinute,
    NSCalendarUnitMonth,
    NSCalendarUnitNanosecond,
    NSCalendarUnitSecond,
    NSCalendarUnitYear,
    NSDate,
    NSObject,
    NSRunLoop,
    NSTextField,
    NSView,
    NSRect,
)
from quickmacapp import Actionable
from twisted.internet.defer import Deferred
from twisted.python.failure import Failure


NSModalResponse = int
T = TypeVar("T")


def asyncModal(alert: NSAlert) -> Deferred[NSModalResponse]:
    """
    Run an NSAlert asynchronously.
    """
    d: Deferred[NSModalResponse] = Deferred()

    def runAndReport() -> None:
        try:
            NSApp().activateIgnoringOtherApps_(True)
            result = alert.runModal()
        except:
            d.errback()
        else:
            d.callback(result)

    NSRunLoop.currentRunLoop().performBlock_(runAndReport)
    return d


def _alertReturns() -> Iterator[NSModalResponse]:
    """
    Enumerate the values used by NSAlert for return values in the order of the
    buttons that occur.
    """
    yield NSAlertFirstButtonReturn
    yield NSAlertSecondButtonReturn
    yield NSAlertThirdButtonReturn
    i = 1
    while True:
        yield NSAlertThirdButtonReturn + i
        i += 1


async def getChoice(title: str, description: str, values: Iterable[tuple[T, str]]) -> T:
    """
    Allow the user to choose between the given values, on buttons labeled in
    the given way.
    """
    msg = NSAlert.alloc().init()
    msg.setMessageText_(title)
    msg.setInformativeText_(description)
    potentialResults = {}
    for (value, label), alertReturn in zip(values, _alertReturns()):
        msg.addButtonWithTitle_(label)
        potentialResults[alertReturn] = value
    msg.layout()
    return potentialResults[await asyncModal(msg)]


async def getString(title: str, question: str, defaultValue: str) -> str | None:
    """
    Prompt the user for some text.
    """
    msg = NSAlert.alloc().init()
    msg.addButtonWithTitle_("OK")
    msg.addButtonWithTitle_("Cancel")
    msg.setMessageText_(title)
    msg.setInformativeText_(question)

    txt = NSTextField.alloc().initWithFrame_(NSRect((0, 0), (200, 100)))
    txt.setMaximumNumberOfLines_(5)
    txt.setStringValue_(defaultValue)
    msg.setAccessoryView_(txt)
    msg.window().setInitialFirstResponder_(txt)
    msg.layout()

    response: NSModalResponse = await asyncModal(msg)

    if response == NSAlertFirstButtonReturn:
        result: str = txt.stringValue()
        return result

    return None
