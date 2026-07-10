from crypto_edge.alerts.whatsapp import WhatsAppAlerter
from crypto_edge.bot.service import BotService
from crypto_edge.config import Settings


def test_whatsapp_disabled_by_default():
    w = WhatsAppAlerter(provider="none")
    assert w.enabled is False


def test_bot_service_status_shape():
    b = BotService()
    s = b.status()
    assert "running" in s
    assert s["running"] is False
    assert "symbols" in s


def test_settings_web_defaults():
    s = Settings()
    assert s.web_port == 8080
    assert s.whatsapp_provider == "none"
    assert s.auto_start_bot is True
    assert s.trade_cooldown_sec >= 0
