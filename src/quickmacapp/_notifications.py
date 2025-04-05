from __future__ import annotations

from dataclasses import dataclass
from zoneinfo import ZoneInfo
from types import TracebackType
from typing import Any, Awaitable, Callable, Protocol, TypeAlias

from datetype import DateTime

from Foundation import NSError, NSLog, NSObject, NSDateComponents
from objc import object_property
from twisted.internet.defer import Deferred
from UserNotifications import (
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
    UNUserNotificationCenter,
)


def make[T: NSObject](cls: type[T], **attributes: object) -> T:
    self: T = cls.alloc().init()
    self.setValuesForKeysWithDictionary_(attributes)
    return self


@dataclass
class _AppNotificationsCtxBuilder:
    _center: UNUserNotificationCenter
    _cfg: _NotifConfigImpl | None

    async def __aenter__(self) -> _NotifConfigImpl:
        """
        Request authorization, then start building this notifications manager.
        """
        NSLog("beginning build")
        grantDeferred: Deferred[bool] = Deferred()

        def completed(granted: bool, error: NSError | None) -> None:
            # TODO: convert non-None NSErrors into failures on this Deferred
            grantDeferred.callback(granted)
            NSLog(
                "Notification authorization response: %@ with error: %@", granted, error
            )

        NSLog("requesting authorization")
        self._center.requestAuthorizationWithOptions_completionHandler_(
            UNAuthorizationOptionNone, completed
        )
        NSLog("requested")
        granted = await grantDeferred
        settingsDeferred: Deferred[UNNotificationSettings] = Deferred()

        def gotSettings(settings: UNNotificationSettings) -> None:
            NSLog("received notification settings %@", settings)
            settingsDeferred.callback(settings)

        NSLog("requesting notification settings")
        self._center.getNotificationSettingsWithCompletionHandler_(gotSettings)
        settings = await settingsDeferred
        NSLog("initializing config")
        self.cfg = _NotifConfigImpl(
            self._center,
            [],
            _wasGrantedPermission=granted,
            _settings=settings,
        )
        NSLog("done!")
        return self.cfg

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool:
        """
        Finalize the set of notification categories and actions in use for this application.
        """
        NSLog("async exit from ctx manager")
        if traceback is None and self.cfg is not None:
            qmandw = _QMANotificationDelegateWrapper.alloc().initWithConfig_(self.cfg)
            qmandw.retain()
            NSLog("Setting delegate! %@", qmandw)
            self._center.setDelegate_(qmandw)
            self.cfg._register()
        else:
            NSLog("NOT setting delegate!!!")
        return False


class _QMANotificationDelegateWrapper(NSObject):
    """
    UNUserNotificationCenterDelegate implementation.
    """

    config: _NotifConfigImpl = object_property()

    def initWithConfig_(self, cfg: _NotifConfigImpl) -> _QMANotificationDelegateWrapper:
        self.config = cfg
        return self

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notification: UNNotification,
        completionHandler: Callable[[UNNotificationPresentationOptions], None],
    ) -> None:
        NSLog("willPresent: %@", notification)
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
        NSLog("received notification repsonse %@", notificationResponse)

        # TODO: actually hook up the dispatch of the notification response to
        # the registry of action callbacks already set up in
        # NotificationConfig.
        async def respond() -> None:
            notifier = self.config._notifierByCategory(
                notificationResponse.notification()
                .request()
                .content()
                .categoryIdentifier()
            )
            await notifier._handleResponse(notificationResponse)
            completionHandler()

        Deferred.fromCoroutine(respond()).addErrback(
            lambda error: NSLog("error: %@", error)
        )


class NotificationTranslator[T](Protocol):
    """
    Translate notifications from the notification ID and some user data,
    """

    def fromNotification(self, notificationID: str, userData: dict[str, Any]) -> T:
        """
        A user interacted with a notification with the given parameters;
        deserialize them into a Python object that can process that action.
        """

    def toNotification(self, notification: T) -> tuple[str, dict[str, Any]]:
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

    # Public interface:
    def undeliver(self, notification: NotifT) -> None:
        """
        Remove the previously-delivered notification object from the
        notification center, if it's still there.
        """
        notID, _ = self._tx.toNotification(notification)
        self._cfg._center.removeDeliveredNotificationsWithIdentifiers_([notID])

    def unsend(self, notification: NotifT) -> None:
        """
        Prevent the as-yet undelivered notification object from being
        delivered.
        """
        notID, _ = self._tx.toNotification(notification)
        self._cfg._center.removePendingNotificationRequestsWithIdentifiers_([notID])

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

    # Attributes:
    _notificationCategoryID: str
    _cfg: _NotifConfigImpl
    _tx: NotificationTranslator[NotifT]
    _actionInfos: list[_oneActionInfo]
    _allowInCarPlay: bool
    _hiddenPreviewsShowTitle: bool
    _hiddenPreviewsShowSubtitle: bool

    # Private implementation details:
    async def _handleResponse(self, response: UNNotificationResponse) -> None:
        userInfo = response.notification().request().content().userInfo()
        actionID: str = response.actionIdentifier()
        notificationID: str = response.notification().request().identifier()
        cat = self._tx.fromNotification(notificationID, userInfo)
        for cb, eachActionID, action, options in self._actionInfos:
            if actionID == eachActionID:
                break
        else:
            raise KeyError(actionID)
        await cb(cat, response)

    def _createUNNotificationCategory(self) -> UNNotificationCategory:
        actions = []
        # We don't yet support intent identifiers.
        intentIdentifiers: list[str] = []
        options = 0
        for handler, actionID, toRegister, extraOptions in self._actionInfos:
            options |= extraOptions
            if toRegister is not None:
                actions.append(toRegister)
        NSLog("actions generated: %@ options: %@", actions, options)
        if self._allowInCarPlay:
            # Ha ha. Someday, maybe.
            options |= UNNotificationCategoryOptionAllowInCarPlay
        if self._hiddenPreviewsShowTitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowTitle
        if self._hiddenPreviewsShowSubtitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowSubtitle
        return UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
            self._notificationCategoryID, actions, intentIdentifiers, options
        )

    async def _notifyWithTrigger(
        self,
        trigger: UNNotificationTrigger,
        notification: NotifT,
        title: str,
        body: str,
    ) -> None:
        notificationID, userInfo = self._tx.toNotification(notification)
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            notificationID,
            make(
                UNMutableNotificationContent,
                title=title,
                body=body,
                categoryIdentifier=self._notificationCategoryID,
                userInfo=userInfo,
            ),
            trigger,
        )
        d: Deferred[NSError | None] = Deferred()
        self._cfg._center.addNotificationRequest_withCompletionHandler_(
            request, d.callback
        )
        error = await d
        NSLog("completed notification request with error %@", error)


@dataclass
class _NotifConfigImpl:
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
        catid: str = f"{category.__module__}.{category.__qualname__}"
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

    def _notifierByCategory(self, categoryID: str) -> Notifier[Any]:
        for notifier in self._notifiers:
            if categoryID == notifier._notificationCategoryID:
                return notifier
        raise KeyError(categoryID)

    def _register(self) -> None:
        self._center.setNotificationCategories_(
            [pynot._createUNNotificationCategory() for pynot in self._notifiers]
        )


_ACTION_INFO_ATTR = "__qma_notification_action_info__"


_oneActionInfo = tuple[
    # Action handler to stuff away into dispatch; does the pulling out of
    # userText if necessary
    Callable[[Any, UNNotificationResponse], Awaitable[None]],
    # action ID
    str,
    # the notification action to register; None for default & dismiss
    UNNotificationAction | None,
    UNNotificationCategoryOptions,
]


_anyActionInfo: TypeAlias = (
    "_PlainNotificationActionInfo | _TextNotificationActionInfo | _BuiltinActionInfo"
)


def _getActionInfo(o: object) -> _oneActionInfo | None:
    handler: _anyActionInfo | None = getattr(o, _ACTION_INFO_ATTR, None)
    if handler is None:
        return None
    appCallback: Any = o
    actionID = handler.identifier
    callback = handler._makeCallback(appCallback)
    extraOptions = handler._extraOptions
    return (callback, actionID, handler._toAction(), extraOptions)


def _setActionInfo[T](wrapt: T, actionInfo: _anyActionInfo) -> T:
    setattr(wrapt, _ACTION_INFO_ATTR, actionInfo)
    return wrapt


def _getAllActionInfos(t: type[object]) -> list[_oneActionInfo]:
    result = []
    for attr in dir(t):
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
