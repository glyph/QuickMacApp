from __future__ import annotations

import os
import sys
import traceback
from typing import Callable, Protocol, Any

from objc import ivar, IBAction, super

from Foundation import (
    NSObject,
    NSException,
)

from AppKit import (
    NSApp,
    NSApplication,
    NSEvent,
    NSResponder,
    NSMenu,
    NSImage,
    NSMenuItem,
    NSStatusBar,
    NSVariableStatusItemLength,
)

from PyObjCTools.Debugging import _run_atos, isPythonException
from ExceptionHandling import (  # type:ignore
    NSStackTraceKey,
)


class Actionable(NSObject):
    """
    Wrap a Python no-argument function call in an NSObject with a C{doIt:}
    method.
    """
    _thunk: Callable[[], None]

    def initWithFunction_(self, thunk: Callable[[], None]) -> Actionable:
        """
        Remember the given callable.

        @param thunk: the callable to run in L{doIt_}.
        """
        self._thunk = thunk
        return self

    @IBAction
    def doIt_(self, sender: object) -> None:
        """
        Call the given callable; exposed as an C{IBAction} in case you want IB
        to be able to see it.
        """
        self._thunk()


def menu(title: str, items: list[tuple[str, Callable[[], object]]]) -> NSMenu:
    """
    Construct an NSMenu from a list of tuples describing it.

    @note: Since NSMenu's target attribute is a weak reference, the callable
        objects here are made immortal via an unpaired call to C{retain} on
        their L{Actionable} wrappers.

    @param items: list of pairs of (menu item's name, click action).

    @return: a new Menu tha is not attached to anything.
    """
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
    """

    def __init__(self, text: str | None = None, image: NSImage | None = None) -> None:
        """
        Create a L{Status} with some text to use as its label.

        @param text: The initial label displayed in the menu bar.
        """
        self.item = NSStatusBar.systemStatusBar().statusItemWithLength_(
            NSVariableStatusItemLength
        )
        self.item.button().setEnabled_(True)
        if image is not None:
            self.item.button().setImage_(image)
        elif text is None:
            from __main__ import __file__ as default
            text = os.path.basename(default)
        if text is not None:
            self.item.button().setTitle_(text)

    def menu(self, items: list[tuple[str, Callable[[], object]]]) -> None:
        """
        Set the status drop-down menu.

        @param items: list of pairs of (menu item's name, click action).

        @see: L{menu}
        """
        self.item.setMenu_(menu(self.item.title(), items))


def fmtPythonException(exception: NSException) -> str:
    """
    Format an NSException containing a wrapped PyObjC python exception.
    """
    userInfo = exception.userInfo()
    return "*** Python exception discarded!\n" + "".join(
        traceback.format_exception(
            userInfo["__pyobjc_exc_type__"],
            userInfo["__pyobjc_exc_value__"],
            userInfo["__pyobjc_exc_traceback__"],
        )
    )


def fmtObjCException(exception: NSException) -> str:
    """
    Format an Objective C exception which I{does not} contain a wrapped Python
    exception.

    @return: our best effort to format the stack trace for the given exception.
    """
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
                return "ObjC exception reporting error: cannot run atos"

            stacktrace = pipe.readlines()
            stacktrace.reverse()
            pipe.close()

    if stacktrace is None:
        userInfo = exception.userInfo()
        stack = userInfo.get(NSStackTraceKey)
        if not stack:
            return "ObjC exception reporting error: cannot get stack trace"

        pipe = _run_atos(stack)
        if pipe is None:
            return "ObjC exception reporting error: cannot run atos"

        stacktrace = pipe.readlines()
        stacktrace.reverse()
        pipe.close()

    return (
        "*** ObjC exception '%s' (reason: '%s') discarded\n"
        % (exception.name(), exception.reason())
        + "Stack trace (most recent call last):\n"
        + "\n".join(["  " + line for line in stacktrace])
    )


class QuickApplication(NSApplication):
    """
    QuickMacApp's main application class.

    @ivar keyEquivalentHandler: Set this attribute to a custom L{NSResponder}
        if you want to handle key equivalents outside the responder chain.  (I
        believe this is necessary in some apps because the responder chain can
        be more complicated in LSUIElement apps, but there might be a better
        way to do this.)
    """
    keyEquivalentHandler: NSResponder = ivar()

    def sendEvent_(self, event: NSEvent) -> None:
        """
        Hand off any incoming events to the key equivalent handler.
        """
        if self.keyEquivalentHandler is not None:
            if self.keyEquivalentHandler.performKeyEquivalent_(event):
                return
        super().sendEvent_(event)

    def reportException_(self, exception):
        """
        Override C{[NSApplication reportException:]} to report exceptions more
        legibly to Python developers.
        """
        if isPythonException(exception):
            print(fmtPythonException(exception))
        else:
            print(fmtObjCException(exception))
        sys.stdout.flush()


class MainRunner(Protocol):
    """
    A function which has been decorated with a runMain attribute.
    """
    def __call__(self, reactor: Any) -> None:
        """
        @param reactor: A Twisted reactor, which provides the usual suspects of
            C{IReactorTime}, C{IReactorTCP}, etc.
        """

    runMain: Callable[[], None]

def mainpoint() -> Callable[[Callable[[Any], None]], MainRunner]:
    """
    Add a .runMain attribute to function

    @return: A decorator that adds a .runMain attribute to a function.

        The runMain attribute starts a reactor and calls the original function
        with a running, initialized, reactor.
    """
    def wrapup(appmain: Callable[[Any], None]) -> MainRunner:
        def doIt() -> None:
            from twisted.internet import cfreactor
            import PyObjCTools.AppHelper

            QuickApplication.sharedApplication()

            def myRunner() -> None:
                PyObjCTools.Debugging.installVerboseExceptionHandler()
                PyObjCTools.AppHelper.runEventLoop()

            def myMain() -> None:
                appmain(reactor)

            reactor = cfreactor.install(runner=myRunner)
            reactor.callWhenRunning(myMain)
            reactor.run()
            os._exit(0)

        appMainAsRunner: MainRunner = appmain  # type:ignore[assignment]
        appMainAsRunner.runMain = doIt
        return appMainAsRunner

    return wrapup


def quit() -> None:
    """
    Quit.
    """
    NSApp().terminate_(NSApp())
