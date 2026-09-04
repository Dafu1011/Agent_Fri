import asyncio

from app import server


def test_run_uses_selector_event_loop_for_windows_uvicorn_server(monkeypatch):
    policies = []
    event_loops = []
    cleared_events = []
    configs = []
    served = []

    class FakeSelectorPolicy:
        pass

    class FakeLoop:
        def run_until_complete(self, awaitable):
            served.append(awaitable)

        def close(self):
            event_loops.append("closed")

    class FakeConfig:
        def __init__(self, *args, **kwargs):
            configs.append((args, kwargs))

    class FakeServer:
        def __init__(self, config):
            self.config = config

        def serve(self):
            return "serve-awaitable"

    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakeSelectorPolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: policies.append(policy))
    monkeypatch.setattr(server.asyncio, "SelectorEventLoop", FakeLoop)
    monkeypatch.setattr(server.asyncio, "set_event_loop", lambda loop: cleared_events.append(loop))
    monkeypatch.setattr(server.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(server.uvicorn, "Server", FakeServer)

    server.run(host="127.0.0.1", port=8090, log_level="debug")

    assert isinstance(policies[0], FakeSelectorPolicy)
    assert configs == [
        (
            ("app.main:app",),
            {
                "host": "127.0.0.1",
                "port": 8090,
                "log_level": "debug",
                "reload": False,
            },
        )
    ]
    assert served == ["serve-awaitable"]
    assert event_loops == ["closed"]
    assert cleared_events[0].__class__ is FakeLoop
    assert cleared_events[-1] is None
