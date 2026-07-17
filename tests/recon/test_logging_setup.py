import logging

from src.recon.entrypoints.logging_setup import configure_logging


def test_new_entrypoint_logging_writes_context_without_business_payload(tmp_path):
    configure_logging(
        {"level": "debug", "dir": str(tmp_path), "file_enabled": True},
        verbose=True,
        run_id="2026-07-17T12:00:00+00:00",
        provider="fixture",
    )
    logging.getLogger("contract").info("采集完成：1 条")

    text = (tmp_path / "run-20260717T120000.log").read_text(encoding="utf-8")
    assert "[fixture 2026-07-17T12:00:00+00:00]" in text
    assert "采集完成：1 条" in text
    assert "comment body" not in text
