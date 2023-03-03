QuickMacApp
==============================

.. note::

    This is extremely rough and poorly documented at this point.  While its
    public API is quite small to avoid **undue** churn, it may change quite
    rapidly and if you want to use this to ship an app you probably will want
    to contribute to it as well.

Make it easier to write small applications for macOS in Python, using Twisted.

To get a very basic status menu API:

.. code::
   python

    from quickmacapp import mainpoint, Status, answer, quit
    from twisted.internet.defer import Deferred

    @mainpoint()
    def app(reactor):
        s = Status("☀️ 💣")
        s.menu([("Do Something", lambda: Deferred.fromCoroutine(answer("something"))),
                ("Quit", quit)])
    app.runMain()

Packaging this into a working app bundle is currently left as an exercise for
the reader.

This was originally extracted from https://github.com/glyph/Pomodouroboros/
