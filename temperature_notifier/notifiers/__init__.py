"""Notifier package for sending push notifications."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from temperature_notifier.configuration import HomeAssistantConfiguration, SimplePushConfiguration
from temperature_notifier.notifiers.base import Notifier, NotifierError
from temperature_notifier.notifiers.home_assistant import HomeAssistantNotifier
from temperature_notifier.notifiers.simplepush import SimplePushNotifier

if TYPE_CHECKING:
    from temperature_notifier.configuration import Configuration

logger = logging.getLogger(__name__)

__all__ = ["Notifier", "NotifierError", "create_notifiers"]


def create_notifiers(config: Configuration) -> list[Notifier]:
    """Instantiate notifiers from the validated configuration.

    To add a new notifier type, add its configuration class with the appropriate
    ``type`` Literal, extend the union in ``Configuration.notifiers``, and add a
    corresponding branch here.

    :param config: The validated top-level configuration.
    :return: List of configured notifier instances.
    :raises NotifierError: If an unsupported notifier type is encountered.
    """
    notifiers: list[Notifier] = []
    for notifier_config in config.notifiers:
        if isinstance(notifier_config, SimplePushConfiguration):
            notifiers.append(SimplePushNotifier(key=notifier_config.key))
        elif isinstance(notifier_config, HomeAssistantConfiguration):
            notifiers.append(HomeAssistantNotifier(
                url=notifier_config.url,
                token=notifier_config.token,
                service=notifier_config.service,
            ))
        else:
            raise NotifierError(f"Unsupported notifier type: {notifier_config.type!r}")
    return notifiers
