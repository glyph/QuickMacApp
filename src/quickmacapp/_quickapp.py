from __future__ import annotations

import os
import sys
import traceback
from dataclasses import dataclass
from types import FunctionType
from typing import Any, Callable, Iterable, Protocol, Sequence, Literal

from AppKit import (
    NSApp,
    NSApplication,
    NSEvent,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSResponder,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSControlStateValueOn,
    NSControlStateValueOff,
)
from ExceptionHandling import NSStackTraceKey  # type:ignore
from Foundation import NSException, NSObject
from objc import IBAction, ivar, super
from PyObjCTools.Debugging import _run_atos, isPythonException


def asSelectorString(f: FunctionType) -> str:
    """
    Convert a method on a PyObjC class into a selector string.
    """
    return f.__name__.replace("_", ":")


@dataclass(kw_only=True)
class ItemState:
    """
    The state of a menu item.
    """

    enabled: bool = True
    "Should the menu item be disabled? True if not, False if so."
    checked: bool = False
    "Should the menu item display a check-mark next to itself? True if so, False if not."
    key: str | None = None
    "Should the menu shortcut mnemonic key be set, blank, or derived from the item's title?"


class Actionable(NSObject):
    """
    Wrap a Python no-argument function call in an NSObject with a C{doIt:}
    method.
    """

    _thunk: Callable[[], object]
    _state: ItemState

    def initWithFunction_(self, thunk: Callable[[], None]) -> Actionable:
        """
        Backwards compatibility initializer, creating this L{Actionable} in the
        default L{ItemState}.
        """
        return self.initWithFunction_andState_(thunk, ItemState())

    def initWithFunction_andState_(
        self, thunk: Callable[[], None], state: ItemState
    ) -> Actionable:
        """
        Remember the given callable, and the given menu state.

        @param thunk: the callable to run in L{doIt_}.

        @param state: the initial state of the menu item presentation
        """
        self._thunk = thunk
        self._state = state
        return self

    @IBAction
    def doIt_(self, sender: object) -> None:
        """
        Call the given callable; exposed as an C{IBAction} in case you want IB
        to be able to see it.
        """
        result = self._thunk()
        if isinstance(result, ItemState):
            self._state = result

    def validateMenuItem_(self, item: NSMenuItem) -> bool:
        item.setState_(
            NSControlStateValueOn if self._state.checked else NSControlStateValueOff
        )
        return self._state.enabled


ACTION_METHOD = asSelectorString(Actionable.doIt_)


def _adjust(
    items: Iterable[
        tuple[str, Callable[[], object]] | tuple[str, Callable[[], object], ItemState]
    ],
) -> Iterable[tuple[str, Callable[[], object], ItemState]]:
    for item in items:
        if len(item) == 3:
            yield item
        else:
            yield (*item, ItemState())


ItemSeq = Sequence[
    tuple[str, Callable[[], object]] | tuple[str, Callable[[], object], ItemState]
]


def menu(
    title: str,
    items: ItemSeq,
) -> NSMenu:
    """
    Construct an NSMenu from a list of tuples describing it.

    @note: Since NSMenu's target attribute is a weak reference, the callable
        objects here are made immortal via an unpaired call to C{retain} on
        their L{Actionable} wrappers.

    @param items: list of pairs of (menu item's name, click action).

    @return: a new Menu tha is not attached to anything.
    """
    result = NSMenu.alloc().initWithTitle_(title)
    for subtitle, thunk, state in _adjust(items):
        initialKeyEquivalent = subtitle[0].lower()
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            subtitle,
            ACTION_METHOD,
            initialKeyEquivalent if state.key is None else state.key,
        )
        item.setTarget_(
            Actionable.alloc().initWithFunction_andState_(thunk, state).retain()
        )
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

    def menu(self, items: ItemSeq) -> None:
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

    @ivar keyEquivalentHandler: Set this attribute to a custom C{NSResponder}
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
            import PyObjCTools.AppHelper
            from twisted.internet import cfreactor

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
