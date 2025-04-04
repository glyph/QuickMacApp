from dataclasses import dataclass
from zoneinfo import ZoneInfo

from datetype import aware
from datetime import datetime
from quickmacapp import Status, mainpoint, quit, answer
from quickmacapp.notifications import Notifier, configureNotifications, response
from twisted.internet.defer import Deferred


@dataclass
class category1:
    notificationID: str
    state: list[str]

    @response(identifier="action1", title="First Action")
    async def action1(self) -> None:
        await answer(f"{self.notificationID}\nhere's an answer! {self.state}")

    @response(identifier="action2", title="Text Action").text()
    async def action2(self, text: str) -> None:
        await answer(f"{self.notificationID}\ngot some text\n{text}\n{self.state}")

    @response.default()
    async def defaulted(self) -> None:
        await answer(f"{self.notificationID}\ndefaulted\n{self.state}")

    @response.dismiss()
    async def dismiss(self) -> None:
        await answer(f"{self.notificationID}\ndismissed\n{self.state}")


class ExampleTranslator:
    def fromNotification(
        self, notificationID: str, userData: dict[str, list[str]]
    ) -> category1:
        return category1(notificationID, userData["stateList"])

    def toNotification(
        self, notification: category1
    ) -> tuple[str, dict[str, list[str]]]:
        return (notification.notificationID, {"stateList": notification.state})


async def setupNotifications() -> Notifier[category1]:
    async with configureNotifications() as n:
        cat1notify = n.add(category1, ExampleTranslator())
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
