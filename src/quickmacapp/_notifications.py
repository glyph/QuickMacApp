from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from zoneinfo import ZoneInfo
from types import TracebackType
from typing import Any, Awaitable, Callable, Protocol
from datetime import datetime

from datetype import DateTime, aware

from Foundation import NSError, NSLog, NSObject, NSDateComponents
from objc import object_property
from twisted.internet.defer import Deferred
from UserNotifications import (
    UNNotificationDismissActionIdentifier,
    UNNotificationDefaultActionIdentifier,
    UNNotificationCategoryOptions,
    UNAuthorizationOptionNone,
    UNMutableNotificationContent,
    UNNotification,
    UNNotificationAction,
    UNNotificationActionOptions,
    UNNotificationActionOptionAuthenticationRequired,
    UNNotificationActionOptionDestructive,
    UNNotificationActionOptionForeground,
    UNNotificationCategory,
    UNNotificationCategoryOptionAllowInCarPlay,
    UNNotificationCategoryOptionCustomDismissAction,
    UNNotificationCategoryOptionHiddenPreviewsShowSubtitle,
    UNNotificationCategoryOptionHiddenPreviewsShowTitle,
    UNNotificationPresentationOptionBanner,
    UNNotificationPresentationOptions,
    UNNotificationRequest,
    UNNotificationResponse,
    UNNotificationSettings,
    UNNotificationTrigger,
    UNCalendarNotificationTrigger,
    UNTextInputNotificationAction,
    UNTextInputNotificationResponse,
    UNUserNotificationCenter,
)


@dataclass
class _AppNotificationsCtxBuilder:
    center: UNUserNotificationCenter
    cfg: NotificationConfig | None

    async def __aenter__(self) -> NotificationConfig:
        """
        Request authorization, then start building this notifications manager.
        """
        grantDeferred: Deferred[bool] = Deferred()

        def completed(granted: bool, error: NSError | None) -> None:
            # TODO: convert non-None NSErrors into failures on this Deferred
            NSLog("Requesting notification authorization...")
            grantDeferred.callback(granted)
            NSLog(
                "Notification authorization response: %@ with error: %@", granted, error
            )

        self.center.requestAuthorizationWithOptions_completionHandler_(
            UNAuthorizationOptionNone, grantDeferred
        )
        granted = await grantDeferred
        settingsDeferred: Deferred[UNNotificationSettings]

        def gotSettings(settings: UNNotificationSettings) -> None:
            settingsDeferred.callback(settings)

        self.center.getNotificationSettingsWithCompletionHandler_(gotSettings)
        settings = await settingsDeferred
        self.cfg = NotificationConfig(
            self.center,
            [],
            _wasGrantedPermission=granted,
            _settings=settings,
        )
        return self.cfg

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool:
        if traceback is None and self.cfg is not None:
            self.center.setDelegate_(
                _QMANotificationDelegateWrapper.alloc().initWithConfig_(self.cfg)
            )
            self.cfg._register()
        return False


class _QMANotificationDelegateWrapper(NSObject):
    config: NotificationConfig = object_property()

    def initWithConfig_(self, cfg: NotificationConfig) -> None:
        self.config = cfg

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notification: UNNotification,
        completionHandler: Callable[[UNNotificationPresentationOptions], None],
    ) -> None:
        # TODO: allow for client code to customize this; here we are saying
        # "please present the notification to the user as a banner, even if we
        # are in the foreground".  We should allow for customization on a
        # category basis; rather than @response.something, maybe
        # @present.something, as a method on the python category class?
        completionHandler(UNNotificationPresentationOptionBanner)

    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notificationResponse: UNNotificationResponse,
        completionHandler: Callable[[], None],
    ) -> None:
        """
        We received a response to a notification.
        """
        # TODO: actually hook up the dispatch of the notification response to
        # the registry of action callbacks already set up in
        # NotificationConfig.
        if isinstance(notificationResponse, UNTextInputNotificationResponse):
            pass
        completionHandler()


def configureNotifications() -> AbstractAsyncContextManager[NotificationConfig]:
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
        UNUserNotificationCenter.currentNotificationCenter(), None
    )


type PList = Any


# framework
class NotificationTranslator[T](Protocol):
    """
    Translate notifications from the notification ID and some user data,
    """

    def fromNotification(self, notificationID: str, userData: PList) -> T:
        """
        A user interacted with a notification with the given parameters;
        deserialize them into a Python object that can process that action.
        """

    def toNotification(self, notification: T) -> tuple[str, PList]:
        """
        The application has requested to send a notification to the operating
        system, serialize the Python object represneting this category of
        notification into a 2-tuple of C{notificatcionID}, C{userData} that can
        be encapsulated in a L{UNNotificationRequest}.
        """


@dataclass
class Notifier[NotifT]:
    """
    A notifier for a specific category.
    """

    _notificationCategoryID: str
    _cfg: NotificationConfig
    _tx: NotificationTranslator[NotifT]
    _actionInfos: list[
        tuple[
            # Action handler to stuff away into dispatch; does the pulling out
            # of userText if necessary
            Callable[[Any, UNNotificationResponse], Awaitable[None]],
            # action ID
            str,
            # the notification action to register; None for default & dismiss
            UNNotificationAction | None,
            UNNotificationCategoryOptions,
        ]
    ]
    _allowInCarPlay: bool
    _hiddenPreviewsShowTitle: bool
    _hiddenPreviewsShowSubtitle: bool

    def _createUNNotificationCategory(self) -> UNNotificationCategory:
        actions = []
        options = 0

        for (
            responseHandlerCB,
            actionID,
            actionToRegister,
            extraOptions,
        ) in self._actionInfos:
            actions.append(actionToRegister)

        if self._allowInCarPlay:
            # Ha ha. Someday, maybe.
            options |= UNNotificationCategoryOptionAllowInCarPlay
        if self._hiddenPreviewsShowTitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowTitle
        if self._hiddenPreviewsShowSubtitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowSubtitle
        UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
            self._notificationCategoryID,
            actions,
            [],
            options,
        )

    async def _notifyWithTrigger(
        self,
        trigger: UNNotificationTrigger,
        notification: NotifT,
        title: str,
        body: str,
    ) -> None:

        notificationID, userInfo = self._tx.toNotification(notification)

        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setCategoryIdentifier_(self._notificationCategoryID)

        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            notificationID,
            content,
            trigger,
        )
        d: Deferred[None] = Deferred()

        def notificationRequestCompleted(error: NSError | None) -> None:
            # TODO: translate errors
            NSLog("completed notification request with error %@", error)
            d.callback(None)

        self._cfg._center.addNotificationRequest_withCompletionHandler_(
            request, notificationRequestCompleted
        )
        await d

    async def notifyAt(
        self, when: DateTime[ZoneInfo], notification: NotifT, title: str, body: str
    ) -> None:
        components: NSDateComponents = NSDateComponents.alloc().init()
        repeats: bool = False
        trigger: UNNotificationTrigger = (
            UNCalendarNotificationTrigger.triggerWithDateMatchingComponents_repeats_(
                components,
                repeats,
            )
        )
        await self._notifyWithTrigger(trigger, notification, title, body)


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


@dataclass
class NotificationConfig:
    _center: UNUserNotificationCenter
    _notifiers: list[Notifier[Any]]
    _wasGrantedPermission: bool
    _settings: UNNotificationSettings

    def add[NotifT](
        self,
        category: type[NotifT],
        translator: NotificationTranslator[NotifT],
        allowInCarPlay: bool = False,
        hiddenPreviewsShowTitle: bool = False,
        hiddenPreviewsShowSubtitle: bool = False,
        # customDismissAction: bool = False,
    ) -> Notifier[NotifT]:
        """
        @param category: the category to add

        @param translator: a translator that can load and save a translator.
        """
        catid: str = category.__name__
        notifier = Notifier(
            catid,
            self,
            translator,
            _getAllActionInfos(category),
            _allowInCarPlay=allowInCarPlay,
            _hiddenPreviewsShowTitle=hiddenPreviewsShowTitle,
            _hiddenPreviewsShowSubtitle=hiddenPreviewsShowSubtitle,
        )
        self._notifiers.append(notifier)
        return notifier

    def _register(self) -> None:
        self._center.setNotificationCategories_(
            [pynot._createUNNotificationCategory() for pynot in self._notifiers]
        )


ACTION_INFO_ATTR = "__qma_notification_action_info__"


def _getActionInfo(
    o: object,
) -> (
    tuple[
        # Action handler to stuff away into dispatch; does the pulling out of
        # userText if necessary
        Callable[[Any, UNNotificationResponse], Awaitable[None]],
        # action ID
        str,
        # the notification action to register; None for default & dismiss
        UNNotificationAction | None,
        UNNotificationCategoryOptions,
    ]
    | None
):
    handler: (
        _PlainNotificationActionInfo
        | _TextNotificationActionInfo
        | _BuiltinActionInfo
        | None
    ) = getattr(o, ACTION_INFO_ATTR, None)
    if handler is None:
        return None
    appCallback: Any = o
    actionID = handler.identifier
    callback = handler._makeCallback(appCallback)
    extraOptions = handler._extraOptions
    return (callback, actionID, handler._toAction(), extraOptions)


def _getAllActionInfos(t: type[object]) -> list[
    tuple[
        # Action handler to stuff away into dispatch; does the pulling out of
        # userText if necessary
        Callable[[Any, UNNotificationResponse], Awaitable[None]],
        # action ID
        str,
        # the notification action to register; None for default & dismiss
        UNNotificationAction | None,
        UNNotificationCategoryOptions,
    ]
]:
    result = []
    for attr in dir(_getAllActionInfos):
        actionInfo = _getActionInfo(getattr(t, attr, None))
        if actionInfo is not None:
            result.append(actionInfo)
    return result


def _py2options(
    foreground: bool,
    destructive: bool,
    authenticationRequired: bool,
) -> UNNotificationActionOptions:
    """
    Convert some sensibly-named data types into UNNotificationActionOptions.
    """
    options = 0
    if foreground:
        options |= UNNotificationActionOptionForeground
    if destructive:
        options |= UNNotificationActionOptionDestructive
    if authenticationRequired:
        options |= UNNotificationActionOptionAuthenticationRequired
    return options


@dataclass
class _PlainNotificationActionInfo:
    identifier: str
    title: str
    foreground: bool
    destructive: bool
    authenticationRequired: bool
    _extraOptions: UNNotificationCategoryOptions = 0

    def _makeCallback[T](
        self, appCallback: Callable[[T], Awaitable[None]]
    ) -> Callable[[Any, UNNotificationResponse], Awaitable[None]]:
        async def takesNotification(self: T, response: UNNotificationResponse) -> None:
            await appCallback(self)
            return None

        return takesNotification

    def _toAction(self) -> UNNotificationAction:
        return UNNotificationAction.actionWithIdentifier_title_options_(
            self.identifier,
            self.title,
            _py2options(
                self.foreground,
                self.destructive,
                self.authenticationRequired,
            ),
        )


@dataclass
class _TextNotificationActionInfo:
    identifier: str
    title: str
    foreground: bool
    destructive: bool
    authenticationRequired: bool
    buttonTitle: str
    textPlaceholder: str
    _extraOptions: UNNotificationCategoryOptions = 0

    def _makeCallback[T](
        self, appCallback: Callable[[T, str], Awaitable[None]]
    ) -> Callable[[Any, UNNotificationResponse], Awaitable[None]]:
        async def takesNotification(self: T, response: UNNotificationResponse) -> None:
            await appCallback(self, response.userText())
            return None

        return takesNotification

    def _toAction(self) -> UNNotificationAction:
        return UNTextInputNotificationAction.actionWithIdentifier_title_options_textInputButtonTitle_textInputPlaceholder_(
            self.identifier,
            self.title,
            _py2options(
                self.foreground,
                self.destructive,
                self.authenticationRequired,
            ),
            self.buttonTitle,
            self.textPlaceholder,
        )


@dataclass
class _BuiltinActionInfo:
    identifier: str
    _extraOptions: UNNotificationCategoryOptions

    def _toAction(self) -> None:
        return None

    def _makeCallback[T](
        self, appCallback: Callable[[T], Awaitable[None]]
    ) -> Callable[[Any, UNNotificationResponse], Awaitable[None]]:
        async def takesNotification(self: T, response: UNNotificationResponse) -> None:
            await appCallback(self)
            return None

        return takesNotification


class response:
    """
    Namespace for response declarations.
    """

    @staticmethod
    def action[NotificationT](
        *,
        identifier: str,
        title: str,
        foreground: bool = False,
        destructive: bool = False,
        authenticationRequired: bool = False,
    ) -> Callable[[Action[NotificationT]], Action[NotificationT]]:
        def deco(wrapt: Action[NotificationT]) -> Action[NotificationT]:
            setattr(
                wrapt,
                ACTION_INFO_ATTR,
                _PlainNotificationActionInfo(
                    identifier=identifier,
                    title=title,
                    foreground=foreground,
                    destructive=destructive,
                    authenticationRequired=authenticationRequired,
                ),
            )
            return wrapt

        return deco

    @staticmethod
    def text[NotificationT](
        *,
        identifier: str,
        title: str,
        buttonTitle: str,
        textPlaceholder: str,
        foreground: bool = False,
        destructive: bool = False,
        authenticationRequired: bool = False,
    ) -> Callable[[TextAction[NotificationT]], TextAction[NotificationT]]:
        def deco(wrapt: TextAction[NotificationT]) -> TextAction[NotificationT]:
            setattr(
                wrapt,
                ACTION_INFO_ATTR,
                _TextNotificationActionInfo(
                    identifier=identifier,
                    title=title,
                    buttonTitle=buttonTitle,
                    textPlaceholder=textPlaceholder,
                    foreground=foreground,
                    destructive=destructive,
                    authenticationRequired=authenticationRequired,
                ),
            )
            return wrapt

        return deco

    @staticmethod
    def default[NotificationT]() -> (
        Callable[[Action[NotificationT]], Action[NotificationT]]
    ):
        # UNNotificationDefaultActionIdentifier
        def deco(wrapt: Action[NotificationT]) -> Action[NotificationT]:
            setattr(
                wrapt,
                ACTION_INFO_ATTR,
                _BuiltinActionInfo(UNNotificationDefaultActionIdentifier, 0),
            )
            return wrapt

        return deco

    @staticmethod
    def dismiss[NotificationT]() -> (
        Callable[[Action[NotificationT]], Action[NotificationT]]
    ):
        # UNNotificationDismissActionIdentifier
        def deco(wrapt: Action[NotificationT]) -> Action[NotificationT]:
            setattr(
                wrapt,
                ACTION_INFO_ATTR,
                _BuiltinActionInfo(
                    UNNotificationDismissActionIdentifier,
                    UNNotificationCategoryOptionCustomDismissAction,
                ),
            )
            return wrapt

        return deco


# ---- ^^^^^ framework cut here ^^^^^ ----


@dataclass
class category1:
    notificationID: str
    state: list[str]

    @response.action(identifier="action1", title="First Action")
    async def action1(self) -> None:
        """
        An action declared like so is a regular action that displays a button.
        """

    @response.text(
        identifier="action2",
        title="Text Action",
        buttonTitle="Process Text",
        textPlaceholder="hold place please",
    )
    async def action2(self, text: str) -> None:
        """
        An action that takes a C{text} argument is registered as a
        L{UNTextInputNotificationAction}, and that text is passed along in
        responses.
        """

    @response.default()
    async def defaulted(self) -> None:
        """
        A user invoked the default response (i.e.: clicked on the
        notification).
        """

    @response.dismiss()
    async def dismiss(self) -> None:
        """
        A user dismissed this notification.
        """


@dataclass
class ExampleTranslator:
    txState: str

    def fromNotification(self, notificationID: str, userData: PList) -> category1:
        return category1(notificationID, userData)

    def toNotification(self, notification: category1) -> tuple[str, PList]:
        return (notification.notificationID, notification.state)


async def setupNotificationsExample() -> None:
    cat1txl = ExampleTranslator("hi")
    async with configureNotifications() as n:
        cat1notify = n.add(category1, cat1txl)
    await cat1notify.notifyAt(
        aware(datetime.now(ZoneInfo("US/Pacific")), ZoneInfo),
        category1("just.testing", ["some", "words"]),
        "Just Testing This Out",
        "Here's The Notification",
    )
