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
    _BuiltinActionInfo,
    _PlainNotificationActionInfo,
    _setActionInfo,
    _TextNotificationActionInfo,
    _AppNotificationsCtxBuilder,
)

__all__ = [
    "NotificationTranslator",
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
    Configure notifications for the current application.

    This is an asynchronous (using Twisted's Deferred) context manager, run
    with `with` statement, which works like this::

        async with configureNotifications() as cfg:
            notifier = cfg.add(MyNotificationData, MyNotificationLoader())

    Each L{add <NotificationConfig.add>} invocation adds a category of
    notifications you can send, and returns an object (a L{Notifier}) that can
    send that category of notification.

    At the end of the C{async with} block, the notification configuration is
    finalized, its state is sent to macOS, and the categories of notification
    your application can send is frozen for the rest of the lifetime of your
    process; the L{Notifier} objects returned from L{add
    <NotificationConfig.add>} are now active nad can be used.  Note that you
    may only call L{configureNotifications} once in your entire process, so you
    will need to pass those notifiers elsewhere!

    Each call to add requires 2 arguments: a notification-data class which
    stores the sent notification's ID and any other ancillary data transmitted
    along with it, and an object that can load and store that first class, when
    notification responses from the operating system convey data that was
    previously scheduled as a notification.  In our example above, they can be
    as simple as this::

        class MyNotificationData:
            id: str

        class MyNotificationLoader:
            def fromNotification(
                self, notificationID: str, userData: dict[str, object]
            ) -> MyNotificationData:
                return MyNotificationData(notificationID)
            def toNotification(
                self,
                notification: MyNotificationData,
            ) -> tuple[str, dict[str, object]]:
                return (notification.id, {})

    Then, when you want to I{send} a notification, you can do::

        await notifier.notifyAt(
            aware(datetime.now(TZ) + timedelta(seconds=5), TZ),
            MyNotificationData("my.notification.id.1"),
            "Title Here",
            "Subtitle Here",
        )

    And that will show the user a notification.

    The C{MyNotificationData} class might seem simplistic to the point of
    uselessness, and in this oversimplified case, it is!  However, if you are
    sending notifications to a user, you really need to be able to I{respond}
    to notifications from a user, and that's where your notification data class
    as well as L{responder} comes in.  To respond to a notification when the
    user clicks on it, you can add a method like so::

        class MyNotificationData:
            id: str

            @response(identifier="response-action-1", title="Action 1")
            async def responseAction1(self) -> None:
                await answer("User pressed 'Action 1' button")

            @response.default()
            async def userClicked(self) -> None:
                await answer("User clicked the notification.")

    When sent with L{Notifier.notifyAt}, your C{MyNotificationData} class will
    be serialized and deserialized with C{MyNotificationLoader.toNotification}
    (converting your Python class into a macOS notification, to send along to
    the OS) and C{MyNotificationLoader.fromNotification} (converting the data
    sent along with the user's response back into a L{MyNotificationData}).

    @note: If your app schedules a notification, then quits, when the user
        responds (clicks on it, uses a button, dismisses it, etc) then the OS
        will re-launch your application and send the notification data back in,
        which is why all the serialization and deserialization is required.
        Your process may have exited and thus the original notification will no
        longer be around.  However, if you are just running as a Python script,
        piggybacking on the 'Python Launcher' app bundle, macOS will not be
        able to re-launch your app.  Notifications going back to the same
        process seem to work okay, but note that as documented, macOS really
        requires your application to have its own bundle and its own unique
        CFBundleIdentifier in order to avoid any weird behavior.
    """
    return _AppNotificationsCtxBuilder(
        _UNUserNotificationCenter.currentNotificationCenter(), None
    )
