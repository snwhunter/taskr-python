"""Environment-only configuration; credentials and secrets are never stored here."""

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class SheetsConfig:
    spreadsheet_id: str
    db_worksheet: str = "db"
    log_worksheet: str = "log"
    credentials_file: str | None = None

    @classmethod
    def from_env(cls) -> "SheetsConfig":
        spreadsheet_id = os.environ.get("TASKR_SPREADSHEET_ID", "").strip()
        if not spreadsheet_id:
            raise ValueError("TASKR_SPREADSHEET_ID is required")
        return cls(
            spreadsheet_id=spreadsheet_id,
            db_worksheet=os.environ.get("TASKR_DB_WORKSHEET", "db"),
            log_worksheet=os.environ.get("TASKR_LOG_WORKSHEET", "log"),
            credentials_file=os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or None,
        )

    def open_worksheets(self):
        """Authenticate with ADC/a service-account file and return ``(db, log)``."""
        import gspread

        if self.credentials_file:
            client = gspread.service_account(filename=self.credentials_file)
        else:
            from google.auth import default

            credentials, _ = default(scopes=gspread.auth.DEFAULT_SCOPES)
            client = gspread.authorize(credentials)
        book = client.open_by_key(self.spreadsheet_id)
        return book.worksheet(self.db_worksheet), book.worksheet(self.log_worksheet)
