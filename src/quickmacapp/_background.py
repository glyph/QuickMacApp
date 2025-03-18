from typing import Any, Callable

from dataclasses import dataclass, field

from AppKit import (
    NSApplication,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSLog,
    NSNotification,
    NSNotificationCenter,
    NSRunningApplication,
    NSWindow,
    NSWindowWillCloseNotification,
    NSWorkspace,
    NSWorkspaceActiveSpaceDidChangeNotification,
    NSWorkspaceApplicationKey,
    NSWorkspaceDidActivateApplicationNotification,
    NSWorkspaceDidHideApplicationNotification,
)


@dataclass
class SometimesBackground:
    """
    An application that is sometimes in the background but has a window that,
    when visible, can own the menubar, become key, etc.  However, when that
    window is closed, we withdraw to the menu bar and continue running in the
    background, as an accessory.
    """

    mainWindow: NSWindow
    hideIconOnOtherSpaces: bool
    onSpaceChange: Callable[[], None]
    currentlyRegular: bool = False
    previouslyActiveApp: NSRunningApplication = field(init=False)

    def someApplicationActivated_(self, notification: Any) -> None:
        # NSLog(f"active {notification} {__file__}")
        whichApp = notification.userInfo()[NSWorkspaceApplicationKey]

        if whichApp == NSRunningApplication.currentApplication():
            if self.currentlyRegular:
                # NSLog("show editor window")
                self.mainWindow.setIsVisible_(True)
            else:
                # NSLog("reactivate workaround")
                self.currentlyRegular = True
                self.previouslyActiveApp.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
                app = NSApplication.sharedApplication()
                app.setActivationPolicy_(NSApplicationActivationPolicyRegular)
                self.mainWindow.setIsVisible_(True)
                from twisted.internet import reactor

                reactor.callLater(  # type:ignore[attr-defined]
                    0.1, lambda: app.activateIgnoringOtherApps_(True)
                )
        else:
            self.previouslyActiveApp = whichApp

    def someApplicationHidden_(self, notification: Any) -> None:
        """
        An app was hidden.
        """
        whichApp = notification.userInfo()[NSWorkspaceApplicationKey]
        if whichApp == NSRunningApplication.currentApplication():
            # 'hide others' (and similar functionality) should *not* hide the
            # progress window; that would obviate the whole point of having
            # this app live in the background in order to maintain a constant
            # presence in the user's visual field.  however if we're being told
            # to hide, don't ignore the user, hide the main window and retreat
            # into the background as if we were closed.
            self.mainWindow.close()
            app = NSApplication.sharedApplication()
            app.unhide_(self)

    def someSpaceActivated_(self, notification: NSNotification) -> None:
        """
        Sometimes, fullscreen application stop getting the HUD overlay.
        """
        menuBarOwner = NSWorkspace.sharedWorkspace().menuBarOwningApplication()
        # me = NSRunningApplication.currentApplication()
        NSLog("space activated where allegedly %@ owns the menu bar", menuBarOwner)
        if not self.mainWindow.isOnActiveSpace():
            if self.hideIconOnOtherSpaces:
                NSLog("I am not on the active space, closing the window")
                self.mainWindow.close()
            else:
                NSLog("I am not on the active space, but that's OK, leaving window open.")
        else:
            NSLog("I am on the active space; not closing.")
        self.onSpaceChange()

    def someWindowWillClose_(self, notification: NSNotification) -> None:
        """
        The main window that we're observing will close.
        """
        if notification.object() == self.mainWindow:
            self.currentlyRegular = False
            NSApplication.sharedApplication().setActivationPolicy_(
                NSApplicationActivationPolicyAccessory
            )

    def startObserving(self) -> None:
        """
        Attach the various callbacks.
        """
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "someWindowWillClose:", NSWindowWillCloseNotification, None
        )
        wsnc = NSWorkspace.sharedWorkspace().notificationCenter()

        self.previouslyActiveApp = (
            NSWorkspace.sharedWorkspace().menuBarOwningApplication()
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someApplicationActivated:",
            NSWorkspaceDidActivateApplicationNotification,
            None,
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someApplicationHidden:",
            NSWorkspaceDidHideApplicationNotification,
            None,
        )

        wsnc.addObserver_selector_name_object_(
            self,
            "someSpaceActivated:",
            NSWorkspaceActiveSpaceDidChangeNotification,
            None,
        )


def dockIconWhenVisible(
    mainWindow: NSWindow,
    hideIconOnOtherSpaces: bool = True,
    onSpaceChange: Callable[[], None] = lambda: None,
):
    """
    When the given main window is visible, we should have a dock icon (i.e.: be
    NSApplicationActivationPolicyRegular).  When our application is activated,
    (i.e.: the user launches it from Spotlight, Finder, or similar) we should
    make the window visible so that the dock icon appears.  When that window is
    then closed, or when our application is hidden, we should hide our dock
    icon (i.e.: be NSApplicationActivationPolicyAccessory).
    """
    SometimesBackground(mainWindow, hideIconOnOtherSpaces, onSpaceChange).startObserving()
