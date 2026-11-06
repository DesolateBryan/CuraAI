"""The suite cannot call a live model: tests/conftest.py blocks the network for every test."""

import urllib.request

import pytest

from curaai.adapters.model.groq_transport import GroqTransport, groq_poster
from curaai.adapters.model.http_transport import ModelHttpError


def test_a_real_http_call_is_blocked_inside_the_test_suite():
    with pytest.raises(Exception) as info:
        urllib.request.urlopen("https://api.groq.com/openai/v1/models", timeout=2)
    assert "must not reach the network" in str(info.value) or "LiveNetworkBlocked" in repr(info.value)


def test_even_a_fully_wired_real_transport_cannot_reach_the_vendor():
    transport = GroqTransport("gsk_fake", poster=groq_poster(), sleep=lambda s: None)
    with pytest.raises((ModelHttpError, Exception)) as info:
        transport.send("S", '{"ping": true}', 20)
    assert "must not reach the network" in str(info.value)
