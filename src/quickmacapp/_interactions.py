from typing import Iterable, Iterator, TypeVar

from AppKit import (
    NSAlertFirstButtonReturn,
    NSAlertSecondButtonReturn,
    NSAlertThirdButtonReturn,
    NSAlert,
    NSApp,
    NSTextField,
    NSSecureTextField,
    NSCenterTextAlignment,
)
from Foundation import (
    NSRunLoop,
    NSRect,
)
from twisted.internet.defer import Deferred


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


async def choose(values: Iterable[tuple[T, str]], question: str, description: str="") -> T:
    """
    Prompt the user to choose between the given values, on buttons labeled in
    the given way.
    """
    msg = NSAlert.alloc().init()
    msg.setMessageText_(question)
    msg.setInformativeText_(description)
    potentialResults = {}
    for (value, label), alertReturn in zip(values, _alertReturns()):
        msg.addButtonWithTitle_(label)
        potentialResults[alertReturn] = value
    msg.layout()
    return potentialResults[await asyncModal(msg)]


async def getpass(question: str, description: str="") -> str | None:
    # set a sample value to get a reasonable visual width
    txt = NSSecureTextField.textFieldWithString_("testing " * 4)
    # clear it out because of course we don't want to use that value
    txt.setStringValue_("")
    txt.setAlignment_(NSCenterTextAlignment)
    txt.setMaximumNumberOfLines_(5)
    return await _ask(question, description, txt)


async def ask(question: str, description: str="", defaultValue: str=""):
    # TODO: version of this with a NSSecureTextField for entering passwords
    txt = NSTextField.alloc().initWithFrame_(NSRect((0, 0), (200, 100)))
    txt.setMaximumNumberOfLines_(5)
    txt.setStringValue_(defaultValue)
    return await _ask(question, description, txt)


async def _ask(question: str, description: str, txt: NSTextField) -> str | None:
    """
    Prompt the user for a short string of text.
    """
    msg = NSAlert.alloc().init()
    msg.addButtonWithTitle_("OK")
    msg.addButtonWithTitle_("Cancel")
    msg.setMessageText_(question)
    msg.setInformativeText_(description)

    msg.setAccessoryView_(txt)
    msg.window().setInitialFirstResponder_(txt)
    msg.layout()

    response: NSModalResponse = await asyncModal(msg)

    if response == NSAlertFirstButtonReturn:
        result: str = txt.stringValue()
        return result

    return None


async def answer(message: str, description: str="") -> None:
    """
    Give the user a message.
    """
    msg = NSAlert.alloc().init()
    msg.setMessageText_(message)
    msg.setInformativeText_(description)
    # msg.addButtonWithTitle("OK")
    msg.layout()

    await asyncModal(msg)
