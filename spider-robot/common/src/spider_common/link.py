"""Message transport. One async interface, three implementations:

* MqttLink      - paho-mqtt 2.x. AWS IoT Core (mTLS on 8883) in phase 1, a local Mosquitto
                  broker in phase 2. Switching is a settings change, not a code change.
* InMemoryHub   - in-process broker for unit tests and single-process simulation.

paho runs its network loop in its own thread; every callback is handed to the asyncio loop
with call_soon_threadsafe, so the rest of the code is plain single-threaded asyncio.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Protocol

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Message:
    topic: str
    payload: bytes


class Link(Protocol):
    connected: asyncio.Event

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    def publish(
        self, topic: str, payload: bytes | str, qos: int = 0, retain: bool = False
    ) -> bool: ...

    def messages(self) -> AsyncIterator[Message]: ...


def topic_matches(sub: str, topic: str) -> bool:
    return mqtt.topic_matches_sub(sub, topic)


class _Inbox:
    """Bounded queue that drops the oldest message instead of blocking."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=maxsize)
        self.dropped = 0

    def put(self, msg: Message) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.dropped += 1
        self.queue.put_nowait(msg)

    async def iterate(self) -> AsyncIterator[Message]:
        while True:
            yield await self.queue.get()


# --------------------------------------------------------------------------- MQTT
@dataclass(frozen=True)
class MqttSettings:
    host: str
    port: int = 8883
    client_id: str = "spider"
    tls: bool = True
    ca_path: str | None = None  # AmazonRootCA1.pem (AWS) or your own CA (local)
    cert_path: str | None = None  # device certificate
    key_path: str | None = None  # device private key
    keepalive_s: int = 10  # last-will "offline" fires ~1.5x this after a silent drop
    username: str | None = None  # plain loopback listener on the Pi (identity for the ACL)
    password: str | None = None
    reconnect_max_s: int = 30  # back-off ceiling; 2 for a broker on the same machine


class MqttLink:
    def __init__(
        self,
        settings: MqttSettings,
        subscriptions: list[str],
        will: tuple[str, bytes] | None = None,
        will_retain: bool = False,
    ) -> None:
        self.settings = settings
        self._subs = list(subscriptions)
        self._inbox = _Inbox()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.connected = asyncio.Event()
        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.client_id,
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if settings.tls:
            client.tls_set(
                ca_certs=settings.ca_path,
                certfile=settings.cert_path,
                keyfile=settings.key_path,
            )
        if settings.username is not None:
            client.username_pw_set(settings.username, settings.password)
        if will is not None:
            client.will_set(will[0], will[1], qos=1, retain=will_retain)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=1, max_delay=settings.reconnect_max_s)
        # paho keeps QoS 1 messages published while offline and replays them after reconnect.
        # Old robot commands must never be replayed, so keep that queue tiny.
        client.max_queued_messages_set(5)
        self._client = client

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._client.connect_async(
            self.settings.host, self.settings.port, keepalive=self.settings.keepalive_s
        )
        self._client.loop_start()

    async def stop(self) -> None:
        self._client.disconnect()
        self._client.loop_stop()

    def publish(self, topic: str, payload: bytes | str, qos: int = 0, retain: bool = False) -> bool:
        """Thread-safe. Returns False when the message could not be sent (e.g. offline)."""
        if not self.connected.is_set():
            return False
        info = self._client.publish(topic, payload, qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def messages(self) -> AsyncIterator[Message]:
        return self._inbox.iterate()

    # paho thread -> asyncio loop
    def _on_connect(self, client, userdata, flags, reason_code, properties) -> None:
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        # Small control messages must not wait for Nagle + delayed ACK (~40 ms per command).
        sock = client.socket()
        if sock is not None:
            with contextlib.suppress(OSError):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        for topic in self._subs:
            client.subscribe(topic, qos=1)
        log.info("MQTT connected to %s:%s", self.settings.host, self.settings.port)
        assert self._loop is not None
        self._loop.call_soon_threadsafe(self.connected.set)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties) -> None:
        log.warning("MQTT disconnected: %s", reason_code)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self.connected.clear)

    def _on_message(self, client, userdata, msg) -> None:
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._inbox.put, Message(msg.topic, bytes(msg.payload)))


# --------------------------------------------------------------------------- in-memory
@dataclass
class InMemoryHub:
    """A tiny broker living in one process. hub.endpoint([...]) returns a Link."""

    endpoints: list[InMemoryLink] = field(default_factory=list)
    retained: dict[str, Message] = field(default_factory=dict)

    def endpoint(self, subscriptions: list[str]) -> InMemoryLink:
        ep = InMemoryLink(self, subscriptions)
        self.endpoints.append(ep)
        return ep

    def route(self, msg: Message) -> None:
        for ep in self.endpoints:
            if any(topic_matches(sub, msg.topic) for sub in ep.subs):
                ep.inbox.put(msg)


class InMemoryLink:
    def __init__(self, hub: InMemoryHub, subscriptions: list[str]) -> None:
        self.hub = hub
        self.subs = list(subscriptions)
        self.inbox = _Inbox()
        self.connected = asyncio.Event()
        self.published: list[Message] = []

    async def start(self) -> None:
        self.connected.set()
        for msg in self.hub.retained.values():
            if any(topic_matches(sub, msg.topic) for sub in self.subs):
                self.inbox.put(msg)

    async def stop(self) -> None:
        self.connected.clear()

    def publish(self, topic: str, payload: bytes | str, qos: int = 0, retain: bool = False) -> bool:
        if not self.connected.is_set():
            return False
        data = payload.encode() if isinstance(payload, str) else payload
        msg = Message(topic, data)
        self.published.append(msg)
        if retain:
            self.hub.retained[topic] = msg
        self.hub.route(msg)
        return True

    def messages(self) -> AsyncIterator[Message]:
        return self.inbox.iterate()
