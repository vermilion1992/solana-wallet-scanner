"""External, observational instrumentation; application/test sources untouched."""
from __future__ import annotations
import functools
import inspect
import json
import os
from pathlib import Path
import resource
import threading
import time
import pytest

OUT = Path(__file__).resolve().parent
START = time.monotonic()
LOCK = threading.RLock()
TOTALS = {}
GUARD_CALLS = None


def emit(event, **data):
    row = {'elapsed_seconds': round(time.monotonic() - START, 6), 'event': event,
           'pid': os.getpid(), 'thread': threading.current_thread().name,
           'peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, **data}
    with LOCK:
        with (OUT / 'checkpoints.jsonl').open('a') as stream:
            stream.write(json.dumps(row, sort_keys=True) + '\n')


def save_totals():
    with LOCK:
        (OUT / 'function-totals.json').write_text(json.dumps(TOTALS, indent=2, sort_keys=True) + '\n')


def timed(original, name, checkpoints=False, describe=None):
    if getattr(original, '_native_profile_wrapped', False):
        return original
    def begin(args, kwargs):
        detail = describe(args, kwargs) if describe else {}
        if checkpoints:
            emit('function.begin', function=name, **detail)
        return time.monotonic(), detail
    def end(start, detail, result=None, error=None):
        elapsed = time.monotonic() - start
        with LOCK:
            stat = TOTALS.setdefault(name, {'calls': 0, 'total_seconds': 0.0, 'max_seconds': 0.0, 'errors': 0})
            stat['calls'] += 1
            stat['total_seconds'] += elapsed
            stat['max_seconds'] = max(stat['max_seconds'], elapsed)
            stat['errors'] += bool(error)
        if checkpoints:
            if isinstance(result, (bytes, bytearray)):
                detail = {**detail, 'result_bytes': len(result)}
            elif isinstance(result, list):
                detail = {**detail, 'result_rows': len(result)}
            emit('function.end', function=name, duration_seconds=round(elapsed, 6), error=error, **detail)
            save_totals()
    if inspect.iscoroutinefunction(original):
        @functools.wraps(original)
        async def wrapper(*args, **kwargs):
            start, detail = begin(args, kwargs)
            try:
                result = await original(*args, **kwargs)
            except BaseException as exc:
                end(start, detail, error=type(exc).__name__)
                raise
            end(start, detail, result)
            return result
    else:
        @functools.wraps(original)
        def wrapper(*args, **kwargs):
            start, detail = begin(args, kwargs)
            try:
                result = original(*args, **kwargs)
            except BaseException as exc:
                end(start, detail, error=type(exc).__name__)
                raise
            end(start, detail, result)
            return result
    wrapper._native_profile_wrapped = True
    return wrapper


def pytest_configure(config):
    import scanner.app as app_module
    from scanner.storage import Store
    import scanner.report_view as report_view
    import scanner.copy_review as copy_review
    import scanner.archive_input as archive_input
    import scanner.indexed_input as indexed_input
    import fastapi.routing as routing
    from starlette.responses import JSONResponse
    from starlette.testclient import TestClient
    import httpx

    for name in ('evidence', 'list', 'get', 'stats', 'close'):
        original = getattr(Store, name)
        detail = (lambda args, kwargs: {'kind': args[1] if len(args) > 1 else kwargs.get('kind')}) if name in ('list', 'get') else None
        # Hot evidence/get paths are aggregate-only, to keep measurement overhead bounded.
        setattr(Store, name, timed(original, 'Store.' + name, checkpoints=name in ('list', 'stats', 'close'), describe=detail))
    report_view.summary_inputs = timed(report_view.summary_inputs, 'report_view.summary_inputs', True)
    for name in ('qualify_report', 'review_copy_behavior'):
        setattr(copy_review, name, timed(getattr(copy_review, name), 'copy_review.' + name, True))
    for module, names in ((archive_input, ('load_archive',)), (indexed_input, ('load_indexed',))):
        for name in names:
            if hasattr(module, name):
                setattr(module, name, timed(getattr(module, name), module.__name__ + '.' + name, True))
    routing.serialize_response = timed(routing.serialize_response, 'fastapi.serialize_response', True)
    JSONResponse.render = timed(JSONResponse.render, 'JSONResponse.render', True)
    httpx.Response.json = timed(httpx.Response.json, 'httpx.Response.json', True,
                               lambda args, kwargs: {'response_bytes': len(args[0].content), 'status_code': args[0].status_code})
    for name in ('get', 'post'):
        def request_detail(args, kwargs):
            return {'path': str(args[1]) if len(args) > 1 else str(kwargs.get('url'))}
        setattr(TestClient, name, timed(getattr(TestClient, name), 'TestClient.' + name, True, request_detail))
    TestClient.__exit__ = timed(TestClient.__exit__, 'TestClient.__exit__', True)
    original_create_app = app_module.create_app
    @functools.wraps(original_create_app)
    def create_app(*args, **kwargs):
        app = original_create_app(*args, **kwargs)
        visited = set()
        replacements = {}
        selected = {'decorate_report', 'reports', 'report_inputs', 'discovery_cohorts', 'build_report'}
        def visit(function):
            if not inspect.isfunction(function) or getattr(function, '_native_profile_wrapped', False) or id(function) in visited:
                return
            visited.add(id(function))
            for cell in function.__closure__ or ():
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if inspect.isfunction(value) and value.__module__ == 'scanner.app' and not getattr(value, '_native_profile_wrapped', False):
                    visit(value)
                    if value.__name__ in selected:
                        replacement = replacements.setdefault(id(value), timed(value, 'app.' + value.__name__, True))
                        cell.cell_contents = replacement
        for route in app.routes:
            endpoint = getattr(route, 'endpoint', None)
            visit(endpoint)
            if getattr(route, 'path', None) in ('/api/state', '/api/archives/import', '/api/reports/{identifier}', '/api/reports/{identifier}/rebuild'):
                replacement = timed(endpoint, 'endpoint.' + route.path, True)
                route.endpoint = replacement
                route.dependant.call = replacement
        emit('app.instrumentation.ready', nested_functions=sorted(selected), route_count=len(app.routes))
        return app
    app_module.create_app = create_app
    emit('pytest.configure', interpreter=os.path.abspath(os.sys.executable))


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    global GUARD_CALLS
    emit('fixture.setup.begin', fixture=fixturedef.argname)
    result = yield
    emit('fixture.setup.end', fixture=fixturedef.argname, error=bool(result.excinfo))
    if fixturedef.argname == 'guarded' and not result.excinfo:
        GUARD_CALLS = result.get_result()[3]
        emit('offline.guard.ready', calls=dict(GUARD_CALLS))


def pytest_fixture_post_finalizer(fixturedef, request):
    emit('fixture.finalized', fixture=fixturedef.argname,
         guard_calls=dict(GUARD_CALLS) if GUARD_CALLS is not None else None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    emit('pytest.setup.begin', nodeid=item.nodeid)
    yield
    emit('pytest.setup.end', nodeid=item.nodeid)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    emit('pytest.call.begin', nodeid=item.nodeid)
    yield
    emit('pytest.call.end', nodeid=item.nodeid, guard_calls=dict(GUARD_CALLS) if GUARD_CALLS is not None else None)
    save_totals()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_teardown(item):
    emit('pytest.teardown.begin', nodeid=item.nodeid)
    yield
    emit('pytest.teardown.end', nodeid=item.nodeid, guard_calls=dict(GUARD_CALLS) if GUARD_CALLS is not None else None)
    save_totals()


def pytest_runtest_logreport(report):
    emit('pytest.report', phase=report.when, outcome=report.outcome, duration_seconds=report.duration)


def pytest_sessionfinish(session, exitstatus):
    emit('pytest.session.finish', exitstatus=int(exitstatus), guard_calls=dict(GUARD_CALLS) if GUARD_CALLS is not None else None)
    save_totals()
