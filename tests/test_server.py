import asyncio

from app import server


def test_run_sets_windows_selector_policy_before_starting_uvicorn(monkeypatch):
    policies = []
    uvicorn_calls = []

    class FakeSelectorPolicy:
        pass

    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(asyncio, "WindowsSelectorEventLoopPolicy", FakeSelectorPolicy, raising=False)
    monkeypatch.setattr(asyncio, "set_event_loop_policy", lambda policy: policies.append(policy))
    monkeypatch.setattr(
        server.uvicorn,
        "run",
        lambda *args, **kwargs: uvicorn_calls.append((args, kwargs)),
    )

    server.run(host="127.0.0.1", port=8090, log_level="debug", reload=True)

    assert isinstance(policies[0], FakeSelectorPolicy)
    assert uvicorn_calls == [
        (
            ("app.main:app",),
            {
                "host": "127.0.0.1",
                "port": 8090,
                "log_level": "debug",
                "reload": True,
                "loop": server.selector_loop_factory,
            },
        )
    ]


def test_selector_loop_factory_returns_selector_loop_on_windows(monkeypatch):
    monkeypatch.setattr(server.sys, "platform", "win32")

    loop = server.selector_loop_factory()

    try:
        assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()
