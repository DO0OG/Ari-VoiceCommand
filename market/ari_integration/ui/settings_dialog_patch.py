"""settings_dialog.py 확장 탭에 추가할 예시 코드."""

MARKET_BUTTON_SNIPPET = """
market_btn = QPushButton("마켓플레이스 열기")
market_btn.setStyleSheet(secondary_btn_style())
market_btn.clicked.connect(
    lambda: QDesktopServices.openUrl(QUrl("https://ari-marketplace.vercel.app"))
)
pvbox.addWidget(market_btn)
""".strip()
