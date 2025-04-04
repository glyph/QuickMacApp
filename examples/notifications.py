from dataclasses import dataclass
from zoneinfo import ZoneInfo

from datetype import aware
from datetime import datetime
from Foundation import NSLog
from quickmacapp import Status, mainpoint, quit, answer
from quickmacapp._notifications import Notifier, PList, configureNotifications, response
from twisted.internet.defer import Deferred


@dataclass
class category1:
    notificationID: str
    state: list[str]

    @response(identifier="action1", title="First Action")
    async def action1(self) -> None:
        """
        An action declared like so is a regular action that displays a button.
        """
        await answer(f"{self.notificationID}\nhere's an answer! {self.state}")

    @response(identifier="action2", title="Text Action").text()
    async def action2(self, text: str) -> None:
        """
        An action that takes a C{text} argument is registered as a
        L{UNTextInputNotificationAction}, and that text is passed along in
        responses.
        """
        await answer(f"{self.notificationID}\ngot some text\n{text}\n{self.state}")

    @response.default()
    async def defaulted(self) -> None:
        """
        A user invoked the default response (i.e.: clicked on the
        notification).
        """
        await answer(f"{self.notificationID}\ndefaulted\n{self.state}")

    @response.dismiss()
    async def dismiss(self) -> None:
        """
        A user dismissed this notification.
        """
        await answer(f"{self.notificationID}\ndismissed\n{self.state}")


@dataclass
class ExampleTranslator:
    txState: str

    def fromNotification(self, notificationID: str, userData: PList) -> category1:
        return category1(notificationID, userData["stateList"])

    def toNotification(self, notification: category1) -> tuple[str, PList]:
        return (notification.notificationID, {"stateList": notification.state})


async def setupNotifications() -> Notifier[category1]:
    cat1txl = ExampleTranslator("hi")
    NSLog("setting up notifications...")
    async with configureNotifications() as n:
        cat1notify = n.add(category1, cat1txl)
    NSLog("set up!")
    return cat1notify


@mainpoint()
def app(reactor):
    async def stuff() -> None:
        s = Status("💁💬")
        n = 0

        async def doNotify() -> None:
            nonlocal n
            n += 1
            await cat1notify.notifyAt(
                aware(datetime.now(ZoneInfo("US/Pacific")), ZoneInfo),
                category1(f"just.testing.{n}", ["some", "words"]),
                f"Just Testing This Out ({n})",
                "Here's The Notification",
            )

        async def doCancel() -> None:
            cat1notify.undeliver(category1(f"just.testing.{n}", ["ignored"]))

        cat1notify = await setupNotifications()
        s.menu(
            [
                ("Notify", lambda: Deferred.fromCoroutine(doNotify())),
                ("Cancel", lambda: Deferred.fromCoroutine(doCancel())),
                ("Quit", quit),
            ]
        )

    Deferred.fromCoroutine(stuff())


app.runMain()
