import eventlet
eventlet.monkey_patch()
import sys

from functools import partial
import logging
from urlparse import urlparse

from kombu import Connection
from pyrabbit.api import Client
import pytest

running_services = []
all_containers = []


def _get_connection(uri):
    conn = Connection(uri)
    return conn


def pytest_addoption(parser):
    parser.addoption(
        '--blocking-detection',
        action='store_true',
        dest='blocking_detection',
        default=True,
        help='turn on eventlet hub blocking detection')

    parser.addoption(
        "--log-level", action="store",
        default='DEBUG',
        help=("The logging-level for the test run."))

    parser.addoption(
        "--amqp-uri", action="store",
        default='amqp://guest:guest@localhost:5672/nameko',
        help=("The AMQP-URI to connect to rabbit with."))

    parser.addoption(
        "--rabbit-ctl-uri", action="store",
        default='http://guest:guest@localhost:15672',
        help=("The URI for rabbit's management API."))


def pytest_configure(config):
    # monkey patch an encoding attribute onto GreenPipe to
    # satisfy a pytest assertion
    import py
    from eventlet.greenio import GreenPipe
    GreenPipe.encoding = py.std.sys.stdout.encoding

    if config.option.blocking_detection:
        from eventlet import debug
        debug.hub_blocking_detection(True)

    log_level = config.getoption('log_level')
    if log_level is not None:
        log_level = getattr(logging, log_level)
        logging.basicConfig(level=log_level, stream=sys.stderr)


@pytest.fixture
def rabbit_config(request):
    amqp_uri = request.config.getoption('amqp_uri')

    conf = {'amqp_uri': amqp_uri}

    uri = urlparse(amqp_uri)
    conf['vhost'] = uri.path[1:]
    conf['username'] = uri.username
    return conf


@pytest.fixture
def rabbit_manager(request):
    config = request.config

    rabbit_ctl_uri = urlparse(config.getoption('rabbit_ctl_uri'))
    host_port = '{0.hostname}:{0.port}'.format(rabbit_ctl_uri)

    rabbit = Client(
        host_port, rabbit_ctl_uri.username, rabbit_ctl_uri.password)

    return rabbit


@pytest.fixture
def reset_rabbit(request, rabbit_manager, rabbit_config):
    vhost = rabbit_config['vhost']
    username = rabbit_config['username']

    def del_vhost():
        try:
            rabbit_manager.delete_vhost(vhost)
        except:
            pass

    request.addfinalizer(del_vhost)

    del_vhost()

    rabbit_manager.create_vhost(vhost)
    rabbit_manager.set_vhost_permissions(vhost, username, '.*', '.*', '.*')


@pytest.fixture
def get_connection(request, reset_rabbit):
    amqp_uri = request.config.getoption('amqp_uri')
    return partial(_get_connection, amqp_uri)


@pytest.fixture
def connection(request, reset_rabbit):
    amqp_uri = request.config.getoption('amqp_uri')
    return _get_connection(amqp_uri)


@pytest.fixture(autouse=True)
def reset_mock_proxy(request):
    from nameko.testing.proxy import reset_state
    reset_state()


@pytest.fixture
def container_factory(request, reset_rabbit):
    def make_container(service_name, service_cls, config):
        from nameko.service import ServiceContainer
        container = ServiceContainer(service_name, service_cls, config)
        all_containers.append(container)
        return container

    def stop_all_containers():
        for c in all_containers:
            try:
                c.stop()
            except:
                pass
        del all_containers[:]

    request.addfinalizer(stop_all_containers)
    return make_container
