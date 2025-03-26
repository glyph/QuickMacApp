from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from types import TracebackType
from typing import Awaitable, Callable, Sequence

from Foundation import NSError, NSLog, NSObject
from objc import object_property
from twisted.internet.defer import Deferred
from UserNotifications import (
    UNTextInputNotificationResponse,
    UNNotificationRequest,
    UNNotificationTrigger,
    UNAuthorizationOptionNone,
    UNNotificationAction,
    UNMutableNotificationContent,
    UNNotificationActionOptionAuthenticationRequired,
    UNNotificationActionOptionDestructive,
    UNNotificationActionOptionForeground,
    UNNotificationCategory,
    UNNotificationPresentationOptions,
    UNNotificationPresentationOptionBanner,
    UNNotificationCategoryOptionAllowInCarPlay,
    UNNotificationCategoryOptionCustomDismissAction,
    UNNotificationCategoryOptionHiddenPreviewsShowSubtitle,
    UNNotificationCategoryOptionHiddenPreviewsShowTitle,
    UNNotificationSettings,
    UNTextInputNotificationAction,
    UNUserNotificationCenter,
    UNNotification,
    UNNotificationResponse,
)


@dataclass
class AppNotificationAction:
    """
    An L{AppNotificationAction} is an action declared in the process of
    building a L{AppNotificationsManager}.
    """


@dataclass
class _AppNotificationsCtxBuilder:
    center: UNUserNotificationCenter
    mgr: AppNotificationsManager | None

    async def __aenter__(self) -> AppNotificationsManager:
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
        self.mgr = AppNotificationsManager(self.center, granted, settings, [], [])
        return self.mgr

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
        /,
    ) -> bool:
        if traceback is None and self.mgr is not None:
            self.center.setDelegate_(
                AppNotificationsDelegateWrapper.alloc().initWithManager_(self.mgr)
            )
            self.center.setNotificationCategories_(
                [each._unNotificationCategory for each in self.mgr._categories]
            )
        return False


class AppNotificationsDelegateWrapper(NSObject):
    manager: AppNotificationsManager = object_property()

    def initWithManager_(self, mgr: AppNotificationsManager) -> None:
        self.manager = mgr

    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self,
        notificationCenter: UNUserNotificationCenter,
        notification: UNNotification,
        completionHandler: Callable[[UNNotificationPresentationOptions], None],
    ) -> None:
        # TODO: allow for client code to customize this
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
        if isinstance(notificationResponse, UNTextInputNotificationResponse):
            pass
        completionHandler()


@dataclass
class AppNotificationsAction:
    identifier: str
    _mgr: AppNotificationsManager
    _unNotificationAction: UNNotificationAction


@dataclass
class AppNotificationsCategory:
    identifier: str
    actions: Sequence[tuple[AppNotificationsAction, Callable[[str], Awaitable[None]]]]
    intentIdentifiers: Sequence[str]
    _manager: AppNotificationsManager
    _unNotificationCategory: UNNotificationCategory

    async def _notifyWithTrigger(
        self, trigger: UNNotificationTrigger, identifier: str, title: str, body: str
    ) -> None:

        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setBody_(body)
        content.setCategoryIdentifier_(self.identifier)

        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            identifier,
            content,
            trigger,
        )
        d: Deferred[None] = Deferred()

        def notificationRequestCompleted(error: NSError | None) -> None:
            # TODO: translate errors
            NSLog("completed notification request with error %@", error)
            d.callback(None)

        self._manager._center.addNotificationRequest_withCompletionHandler_(
            request, notificationRequestCompleted
        )
        await d


@dataclass
class TextInput:
    buttonTitle: str
    textPlaceholder: str


@dataclass
class AppNotificationsManager:
    """
    An L{AppNotificationsManager} can emit local notifications to the user and
    configure the application's response to the user interacting with those
    notifications.
    """

    _center: UNUserNotificationCenter
    _granted: bool
    _settings: UNNotificationSettings
    _actions: list[AppNotificationsAction]
    _categories: list[AppNotificationsCategory]

    def action(
        self,
        *,
        identifier: str,
        title: str,
        foreground: bool = False,
        destructive: bool = False,
        authenticationRequired: bool = False,
        textInput: TextInput | None = None,
    ) -> AppNotificationsAction:
        # TODO: support for 'icon' parameter

        # compose options
        options = 0
        if foreground:
            options |= UNNotificationActionOptionForeground
        if destructive:
            options |= UNNotificationActionOptionDestructive
        if authenticationRequired:
            options |= UNNotificationActionOptionAuthenticationRequired

        if textInput is not None:
            textInputButtonTitle = textInput.buttonTitle
            textInputPlaceholder = textInput.textPlaceholder
            uiAction = UNTextInputNotificationAction.actionWithIdentifier_title_options_textInputButtonTitle_textInputPlaceholder_(
                identifier, title, options, textInputButtonTitle, textInputPlaceholder
            )
        else:
            uiAction = UNNotificationAction.actionWithIdentifier_title_options_(
                identifier, title, options
            )
        self._actions.append(
            action := AppNotificationsAction(
                identifier,
                self,
                uiAction,
            )
        )
        return action

    def category(
        self,
        *,
        identifier: str,
        actions: Sequence[
            tuple[AppNotificationsAction, Callable[[str], Awaitable[None]]]
        ],
        activated: Callable[[str], Awaitable[None]],
        allowInCarPlay: bool = False,
        hiddenPreviewsShowTitle: bool = False,
        hiddenPreviewsShowSubtitle: bool = False,
        customDismissAction: bool = False,
    ) -> AppNotificationsCategory:
        # Something to do with SiriKit, but we don't know what.
        intentIdentifiers: list[str] = []
        options = 0
        if allowInCarPlay:
            # Ha ha. Someday, maybe.
            options |= UNNotificationCategoryOptionAllowInCarPlay
        if hiddenPreviewsShowTitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowTitle
        if hiddenPreviewsShowSubtitle:
            options |= UNNotificationCategoryOptionHiddenPreviewsShowSubtitle
        if customDismissAction:
            options |= UNNotificationCategoryOptionCustomDismissAction
        self._categories.append(
            result := AppNotificationsCategory(
                identifier=identifier,
                actions=actions,
                intentIdentifiers=intentIdentifiers,
                _unNotificationCategory=UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                    identifier,
                    [action._unNotificationAction for (action, cb) in actions],
                    intentIdentifiers,
                    options,
                ),
                _manager=self,
            )
        )
        return result


def configureNotifications() -> AbstractAsyncContextManager[AppNotificationsManager]:
    return _AppNotificationsCtxBuilder(
        UNUserNotificationCenter.currentNotificationCenter(), None
    )


async def setupNotificationsExample() -> None:
    async with configureNotifications() as n:
        action1 = n.action(identifier="action1", title="Action 1")

        # Every notification needs to have a category identifier in order to be
        # presented.  Notifications within a category thus have a natural
        # association with some logic to execute as a (categoryIdentifier,
        # actionIdentifier) tuple, taking the notification's own identifier
        # itself as an argument, to look up any associated persistent data that
        # may exist across app launches.  There are also the *implied* actions
        # of UNNotificationDefaultActionIdentifier and
        # UNNotificationDismissActionIdentifier, for when the user just clicks
        # on a notification and for when the user dismisses the notification.
        # To make the illegal states unrepresentable here, we need to have a
        # structure like...

        async def action1category1(notificationIdentifier: str) -> None:
            """
            This callback executes when the user presses the action1 button on
            a category1 notification.
            """

        async def action1activated(notificationIdentifier: str) -> None:
            """
            This callback executes when the user clicks on a category1
            notification to activate the application, without selecting an
            action.
            """

        n.category(
            identifier="category1",
            # If you want to specify an action, you _must_ supply a paired callback.
            actions=[(action1, action1category1)],
            activated=action1activated,
        )
