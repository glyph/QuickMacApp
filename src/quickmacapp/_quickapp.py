import os
import sys
import traceback
from typing import Callable

from objc import ivar
from twisted.internet.fdesc import setBlocking


# Prevent tracebacks or other large messages from truncating when debugging
# https://github.com/ronaldoussoren/py2app/issues/444
setBlocking(0)
setBlocking(1)

from Foundation import NSObject
from AppKit import (
    NSApp,
    NSApplication,
    NSEvent,
    NSResponder,
    NSMenu,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)

from PyObjCTools.Debugging import _run_atos, isPythonException
from ExceptionHandling import (  # type:ignore
    NSStackTraceKey,
)


class Actionable(NSObject):
    def initWithFunction_(self, thunk):
        self.thunk = thunk
        return self

    def doIt_(self, sender):
        self.thunk()


def menu(title: str, items: list[tuple[str, Callable[[], object]]]) -> NSMenu:
    result = NSMenu.alloc().initWithTitle_(title)
    for (subtitle, thunk) in items:
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            subtitle, "doIt:", subtitle[0].lower()
        )
        item.setTarget_(Actionable.alloc().initWithFunction_(thunk).retain())
        result.addItem_(item)
    result.update()
    return result


class Status:

    """
    Application status (top menu bar, on right)

    Args:
        text: String, initial status
    """

    def __init__(self, text: str) -> None:
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.item.setTitle_(text)
        self.item.setEnabled_(True)
        self.item.setHighlightMode_(True)

    def menu(self, items: list[tuple[str, Callable[[], object]]]) -> None:
        """
        Set the status drop-down menu

        Args:
            items: list of pairs of menu item name and callable if it is clicked
        """
        self.item.setMenu_(menu(self.item.title(), items))


def fmtPythonException(exception):
    userInfo = exception.userInfo()
    return "*** Python exception discarded!\n" + "".join(
        traceback.format_exception(
            userInfo["__pyobjc_exc_type__"],
            userInfo["__pyobjc_exc_value__"],
            userInfo["__pyobjc_exc_traceback__"],
        )
    )


def fmtObjCException(exception):
    stacktrace = None

    try:
        stacktrace = exception.callStackSymbols()

    except AttributeError:
        pass

    if stacktrace is None:
        stack = exception.callStackReturnAddresses()
        if stack:
            pipe = _run_atos(" ".join(hex(v) for v in stack))
            if pipe is None:
                return True

            stacktrace = pipe.readlines()
            stacktrace.reverse()
            pipe.close()

    if stacktrace is None:
        userInfo = exception.userInfo()
        stack = userInfo.get(NSStackTraceKey)
        if not stack:
            return True

        pipe = _run_atos(stack)
        if pipe is None:
            return True

        stacktrace = pipe.readlines()
        stacktrace.reverse()
        pipe.close()

    return (
        "*** ObjC exception '%s' (reason: '%s') discarded\n"
        % (exception.name(), exception.reason())
        + "Stack trace (most recent call last):\n"
        + "\n".join(["  " + line for line in stacktrace])
    )
    return False


class QuickApplication(NSApplication):
    keyEquivalentHandler: NSResponder = ivar()

    def sendEvent_(self, event: NSEvent) -> None:
        if self.keyEquivalentHandler is not None:
            if self.keyEquivalentHandler.performKeyEquivalent_(event):
                return
        super().sendEvent_(event)

    def reportException_(self, exception):
        if isPythonException(exception):
            print(fmtPythonException(exception))
        else:
            print(fmtObjCException(exception))
        sys.stdout.flush()


def mainpoint():
    """
    Add a .runMain attribute to function

    Returns:
        A decorator that adds a .runMain attribute
        to a function

    The runMain attribute starts a reactor and calls
    the original function with a running, initialized,
    reactor.
    """
    def wrapup(appmain):
        def doIt():
            from twisted.internet import cfreactor
            import PyObjCTools.AppHelper

            QuickApplication.sharedApplication()

            def myRunner():
                PyObjCTools.Debugging.installVerboseExceptionHandler()
                PyObjCTools.AppHelper.runEventLoop()

            def myMain():
                appmain(reactor)

            reactor = cfreactor.install(runner=myRunner)
            reactor.callWhenRunning(myMain)
            reactor.run()
            os._exit(0)

        appmain.runMain = doIt
        return appmain

    return wrapup


def quit():
    """
    Quit.
    """
    NSApp().terminate_(NSApp())
