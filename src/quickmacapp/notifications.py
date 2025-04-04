"""
API for emitting macOS notifications.

@see: L{configureNotifications}.
"""

from contextlib import AbstractAsyncContextManager as _AbstractAsyncContextManager
from dataclasses import dataclass as _dataclass
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

from datetype import DateTime
from UserNotifications import (
    UNNotificationCategoryOptionCustomDismissAction as _UNNotificationCategoryOptionCustomDismissAction,
    UNUserNotificationCenter as _UNUserNotificationCenter,
    UNNotificationDefaultActionIdentifier as _UNNotificationDefaultActionIdentifier,
    UNNotificationDismissActionIdentifier as _UNNotificationDismissActionIdentifier,
)

from quickmacapp._notifications import (
    NotificationTranslator,
    PList,
    _BuiltinActionInfo,
    _PlainNotificationActionInfo,
    _setActionInfo,
    _TextNotificationActionInfo,
    _AppNotificationsCtxBuilder,
)

__all__ = [
    "NotificationTranslator",
    "PList",
    "Action",
    "TextAction",
    "response",
    "Notifier",
    "NotificationConfig",
]


class Action[NotificationT](Protocol):
    """
    An action is just an async method that takes its C{self} (an instance of a
    notification class encapsulating the ID & data), and reacts to the
    specified action.
    """

    async def __call__(__no_self__, /, self: NotificationT) -> None:
        """
        React to the action.
        """


class TextAction[NotificationT](Protocol):
    """
    A L{TextAction} is just like an L{Action}, but it takes some text.
    """

    async def __call__(__no_self__, /, self: NotificationT, text: str) -> None:
        """
        React to the action with the user's input.
        """


@_dataclass
class response:
    identifier: str
    title: str
    foreground: bool = False
    destructive: bool = False
    authenticationRequired: bool = False

    def __call__[NT](self, action: Action[NT], /) -> Action[NT]:
        return _setActionInfo(
            action,
            _PlainNotificationActionInfo(
                identifier=self.identifier,
                title=self.title,
                foreground=self.foreground,
                destructive=self.destructive,
                authenticationRequired=self.authenticationRequired,
            ),
        )

    def text[NT](
        self, *, title: str | None = None, placeholder: str = ""
    ) -> Callable[[TextAction[NT]], TextAction[NT]]:
        return lambda wrapt: _setActionInfo(
            wrapt,
            _TextNotificationActionInfo(
                identifier=self.identifier,
                title=self.title,
                buttonTitle=title if title is not None else self.title,
                textPlaceholder=placeholder,
                foreground=self.foreground,
                destructive=self.destructive,
                authenticationRequired=self.authenticationRequired,
            ),
        )

    @staticmethod
    def default[NT]() -> Callable[[Action[NT]], Action[NT]]:
        return lambda wrapt: _setActionInfo(
            wrapt, _BuiltinActionInfo(_UNNotificationDefaultActionIdentifier, 0)
        )

    @staticmethod
    def dismiss[NT]() -> Callable[[Action[NT]], Action[NT]]:
        return lambda wrapt: _setActionInfo(
            wrapt,
            _BuiltinActionInfo(
                _UNNotificationDismissActionIdentifier,
                _UNNotificationCategoryOptionCustomDismissAction,
            ),
        )


class Notifier[NotifT](Protocol):
    """
    A L{Notifier} can deliver notifications.
    """

    async def notifyAt(
        self, when: DateTime[ZoneInfo], notification: NotifT, title: str, body: str
    ) -> None:
        """
        Request a future notification at the given time.
        """

    def undeliver(self, notification: NotifT) -> None:
        """
        Remove the previously-delivered notification object from the
        notification center, if it's still there.
        """

    def unsend(self, notification: NotifT) -> None:
        """
        Prevent the as-yet undelivered notification object from being
        delivered.
        """


class NotificationConfig(Protocol):

    def add[NotifT](
        self,
        category: type[NotifT],
        translator: NotificationTranslator[NotifT],
        allowInCarPlay: bool = False,
        hiddenPreviewsShowTitle: bool = False,
        hiddenPreviewsShowSubtitle: bool = False,
    ) -> Notifier[NotifT]: ...


def configureNotifications() -> _AbstractAsyncContextManager[NotificationConfig]:
    """
    Configure notifications for the current application, in a context manager.

    This is in a context manager to require the setup to happen at the end with
    the given list of categories.  Use like so::

        class A:
            id: str

            @response.default()
            async def activated(self) -> None:
                print(f"user clicked {self.id}")

        async def buildNotifiers(
            appSpecificNotificationsDB: YourClass
        ) -> tuple[Notifier[A], Notifier[B]]:
            with configureNotifications() as cfg:
                return (cfg.add(A, ATranslator(appSpecificNotificationsDB)),
                        cfg.add(B, BTranslator(appSpecificNotificationsDB)))

    and then in your application, in a startup hook like
    applicationDidFinishLaunching_ or similar ::

        def someSetupEvent_(whatever: NSObject) -> None:
            async def setUpNotifications() -> None:
                self.notifierA, self.notifierB = await buildNotifiers()
            Deferred.fromCoroutine(setUpNotifications())
    """
    return _AppNotificationsCtxBuilder(
        _UNUserNotificationCenter.currentNotificationCenter(), None
    )
