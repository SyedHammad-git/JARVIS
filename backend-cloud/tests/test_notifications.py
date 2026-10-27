"""Server notifications are sent only through online opted-in devices."""
from unittest.mock import patch

from app.notifications import send_discord_alert, send_os_notification


def test_os_notification_dispatches_to_online_device_client():
    with patch("app.notifications.db_read", return_value=[
        {"device_id": "dev-offline", "owner_username": "owner-a"},
        {"device_id": "dev-online", "owner_username": "owner-a"},
    ]) as read_devices, \
            patch("app.devices.gateway.is_online", side_effect=lambda device_id: device_id == "dev-online"), \
            patch("app.devices.gateway.call_device", return_value={"ok": True}) as dispatch:
        assert send_os_notification(
            "Reminder", "Alarm due", timeout=15, owner_username="owner-a"
        )

    read_devices.assert_called_once_with(
        "SELECT device_id, owner_username FROM devices "
        "WHERE revoked=0 AND owner_username=? ORDER BY created_at",
        ("owner-a",),
    )
    dispatch.assert_called_once_with(
        "dev-online",
        "notify",
        {"title": "Reminder", "body": "Alarm due"},
        timeout=10,
        owner_username="owner-a",
    )


def test_os_notification_skips_silently_without_online_device():
    with patch("app.notifications.db_read") as read_devices, \
            patch("app.devices.gateway.call_device") as dispatch:
        assert not send_os_notification("Reminder", "Alarm due")
    read_devices.assert_not_called()
    dispatch.assert_not_called()


def test_discord_notification_reads_only_the_requested_owner_settings():
    with patch("app.notifications.REQUESTS_OK", True), \
            patch("app.notifications.db_read", return_value=[{
                "webhook_url": "", "enabled": 0,
            }]) as read_settings:
        assert not send_discord_alert("Test", owner_username="owner-a")

    read_settings.assert_called_once_with(
        "SELECT webhook_url,enabled FROM discord_settings WHERE owner_username=?",
        ("owner-a",),
    )


def test_discord_notification_without_owner_does_not_read_settings():
    with patch("app.notifications.db_read") as read_settings:
        assert not send_discord_alert("Test")
    read_settings.assert_not_called()
