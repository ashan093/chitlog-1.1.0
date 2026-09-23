"""Printable, branded monthly worker salary slips using Qt's PDF writer."""
from __future__ import annotations

from datetime import date
import os
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPdfWriter,
)

from chitlog.core.money import format_minor
from chitlog.services.worker_work_service import attendance_duration_label


PAYMENT_METHOD_LABELS = {
    "daily": "Daily",
    "per_job": "Per Job",
    "period": "Period",
    "monthly": "Monthly",
}

WORKER_TYPE_LABELS = {
    "permanent": "Permanent",
    "temporary": "Temporary",
}


class SalarySlipError(RuntimeError):
    """Safe PDF-generation error suitable for display in the UI."""


class SalarySlipPdfService:
    """Generate one A4 salary-slip page per selected worker."""

    def __init__(
        self,
        worker_service,
        payroll_service,
        currency_code: str,
        currency_symbol: str,
        logo_path: str | Path | None = None,
    ):
        self.worker_service = worker_service
        self.payroll_service = payroll_service
        self.currency_code = currency_code or "LKR"
        self.currency_symbol = currency_symbol or self.currency_code
        self.logo_path = Path(logo_path) if logo_path else None

    @staticmethod
    def _month_start(value: str) -> date:
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise SalarySlipError("The salary-slip month is invalid.") from None
        return parsed.replace(day=1)

    @staticmethod
    def _month_label(month: date) -> str:
        return month.strftime("%B %Y")

    @staticmethod
    def _month_bounds(month: date) -> tuple[str, str]:
        from calendar import monthrange

        start = month.replace(day=1)
        end = month.replace(day=monthrange(month.year, month.month)[1])
        return start.isoformat(), end.isoformat()

    def _worked_days(self, worker_id: int, month: date):
        """Return active attendance/worked-day records for the selected month."""
        work_service = getattr(self.payroll_service, "work_service", None)
        if work_service is None:
            return []
        start, end = self._month_bounds(month)
        records = work_service.list_attendance_month(worker_id, start, end)
        return sorted(records, key=lambda record: (record.work_date, record.id))

    def _money(self, minor: int) -> str:
        return format_minor(minor, self.currency_code, self.currency_symbol)

    @staticmethod
    def _font(size: int, *, bold: bool = False) -> QFont:
        font = QFont("Segoe UI", size)
        font.setBold(bold)
        return font

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        text: str,
        *,
        size: int = 10,
        bold: bool = False,
        color: QColor | None = None,
        align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    ) -> None:
        painter.setFont(SalarySlipPdfService._font(size, bold=bold))
        painter.setPen(color or QColor("#063154"))
        painter.drawText(rect, align, str(text))

    def _draw_row(
        self,
        painter: QPainter,
        x: float,
        y: float,
        width: float,
        label: str,
        value: str,
        *,
        height: float,
        strong: bool = False,
    ) -> float:
        label_width = width * 0.54
        painter.setPen(QColor("#D4DEE3"))
        painter.drawLine(int(x), int(y + height), int(x + width), int(y + height))
        self._draw_text(
            painter,
            QRectF(x, y, label_width, height),
            label,
            size=10,
            bold=False,
            color=QColor("#526777"),
        )
        self._draw_text(
            painter,
            QRectF(x + label_width, y, width - label_width, height),
            value,
            size=11 if strong else 10,
            bold=strong,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        return y + height

    def _draw_worker_page(
        self,
        painter: QPainter,
        writer: QPdfWriter,
        worker,
        summary,
        month: date,
    ) -> None:
        # QPdfWriter can translate the painter origin when page margins are set.
        # Use a zero-margin PDF page and create our own equal inset from the full
        # A4 page. This keeps the entire slip mathematically centered.
        page = writer.pageLayout().fullRectPixels(writer.resolution())
        inset = writer.resolution() * 12.0 / 25.4  # 12 mm on every side
        left = float(page.left()) + inset
        top = float(page.top()) + inset
        width = float(page.width()) - inset * 2
        height = float(page.height()) - inset * 2

        teal = QColor("#2F9D94")
        deep_teal = QColor("#025F67")
        navy = QColor("#063154")
        muted = QColor("#526777")
        light = QColor("#F7F6F2")
        border = QColor("#CAD7DC")
        white = QColor("#FFFFFF")

        content_x = left + width * 0.052
        content_w = width * 0.896
        pad = content_w * 0.025

        # ------------------------------ header ------------------------------
        header_h = height * 0.085
        painter.fillRect(QRectF(left, top, width, header_h), light)
        painter.fillRect(QRectF(left, top, width * 0.015, header_h), teal)

        logo_drawn = False
        if self.logo_path and self.logo_path.exists():
            image = QImage(str(self.logo_path))
            if not image.isNull():
                scaled = image.scaled(
                    int(width * 0.17),
                    int(header_h * 0.46),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawImage(
                    QRectF(
                        left + width * 0.035,
                        top + header_h * 0.14,
                        scaled.width(),
                        scaled.height(),
                    ),
                    scaled,
                )
                logo_drawn = True

        # Keep the document title itself centered on the A4 page; the logo and
        # small ChitLog brand mark sit at the sides without shifting the title.
        title_rect = QRectF(
            left + width * 0.24,
            top + header_h * 0.13,
            width * 0.52,
            header_h * 0.34,
        )
        month_rect = QRectF(
            left + width * 0.24,
            top + header_h * 0.49,
            width * 0.52,
            header_h * 0.25,
        )
        self._draw_text(
            painter,
            title_rect,
            "SALARY SLIP",
            size=18,
            bold=True,
            color=navy,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._draw_text(
            painter,
            month_rect,
            self._month_label(month),
            size=10,
            color=deep_teal,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._draw_text(
            painter,
            QRectF(left + width * 0.74, top + header_h * 0.46, width * 0.21, header_h * 0.26),
            "ChitLog",
            size=10,
            bold=True,
            color=teal,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        y = top + header_h + height * 0.018

        # -------------------------- worker details --------------------------
        info_h = height * 0.088
        painter.setPen(border)
        painter.setBrush(white)
        painter.drawRoundedRect(QRectF(content_x, y, content_w, info_h), 10, 10)
        row_h = info_h / 2.0

        self._draw_text(
            painter,
            QRectF(content_x + pad, y, content_w * 0.48, row_h),
            worker.name,
            size=14,
            bold=True,
            color=navy,
        )
        self._draw_text(
            painter,
            QRectF(content_x + content_w * 0.52, y, content_w * 0.45 - pad, row_h),
            WORKER_TYPE_LABELS.get(worker.worker_type, worker.worker_type.title()),
            size=9,
            bold=True,
            color=deep_teal,
            align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )

        contact = worker.phone or "No phone recorded"
        worker_meta = (
            f"{PAYMENT_METHOD_LABELS.get(worker.payment_method, worker.payment_method.title())}"
            f"  |  {'Active' if worker.is_active else 'Inactive'}"
            f"  |  Phone: {contact}"
        )
        self._draw_text(
            painter,
            QRectF(content_x + pad, y + row_h, content_w - pad * 2, row_h),
            worker_meta,
            size=9,
            color=muted,
        )
        y += info_h + height * 0.018

        # -------------------------- worked-day list -------------------------
        attendance = self._worked_days(worker.id, month)
        self._draw_text(
            painter,
            QRectF(content_x, y, content_w, height * 0.026),
            f"WORKED DAYS ({len(attendance)})",
            size=10,
            bold=True,
            color=deep_teal,
        )
        y += height * 0.027

        if attendance:
            # Use two compact columns when there are many records. Each attendance
            # entry explicitly says Full day / Half day / X hours so the printed
            # slip reflects the worker's actual attendance detail.
            two_columns = len(attendance) > 10
            column_count = 2 if two_columns else 1
            rows_per_column = (len(attendance) + column_count - 1) // column_count
            list_row_h = height * 0.0165
            gap = content_w * 0.035
            column_w = (content_w - gap) / 2.0 if two_columns else content_w

            for column in range(column_count):
                first = column * rows_per_column
                last = min(len(attendance), first + rows_per_column)
                column_records = attendance[first:last]
                x = content_x + column * (column_w + gap)
                date_w = column_w * 0.38
                duration_w = column_w * 0.31
                amount_w = column_w - date_w - duration_w

                self._draw_text(
                    painter,
                    QRectF(x, y, date_w, list_row_h),
                    "Date",
                    size=8,
                    bold=True,
                    color=muted,
                )
                self._draw_text(
                    painter,
                    QRectF(x + date_w, y, duration_w, list_row_h),
                    "Work time",
                    size=8,
                    bold=True,
                    color=muted,
                )
                self._draw_text(
                    painter,
                    QRectF(x + date_w + duration_w, y, amount_w, list_row_h),
                    "Amount",
                    size=8,
                    bold=True,
                    color=muted,
                    align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                )

                row_y = y + list_row_h
                for record in column_records:
                    try:
                        date_text = date.fromisoformat(record.work_date).strftime("%d %b %Y")
                    except ValueError:
                        date_text = record.work_date
                    duration_text = attendance_duration_label(record)
                    amount_text = self._money(record.amount_minor) if record.amount_minor else "-"

                    painter.setPen(border)
                    painter.drawLine(
                        int(x),
                        int(row_y + list_row_h),
                        int(x + column_w),
                        int(row_y + list_row_h),
                    )
                    self._draw_text(
                        painter,
                        QRectF(x, row_y, date_w, list_row_h),
                        date_text,
                        size=8,
                        color=navy,
                    )
                    self._draw_text(
                        painter,
                        QRectF(x + date_w, row_y, duration_w, list_row_h),
                        duration_text,
                        size=8,
                        color=navy,
                    )
                    self._draw_text(
                        painter,
                        QRectF(x + date_w + duration_w, row_y, amount_w, list_row_h),
                        amount_text,
                        size=8,
                        color=navy,
                        align=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    )
                    row_y += list_row_h

            y += list_row_h * (rows_per_column + 1) + height * 0.015
        else:
            self._draw_text(
                painter,
                QRectF(content_x, y, content_w, height * 0.025),
                "No worked-day records were entered for this month.",
                size=9,
                color=muted,
            )
            y += height * 0.038

        # ------------------------- payroll breakdown ------------------------
        self._draw_text(
            painter,
            QRectF(content_x, y, content_w, height * 0.026),
            "PAYROLL BREAKDOWN",
            size=10,
            bold=True,
            color=deep_teal,
        )
        y += height * 0.028

        row_height = height * 0.032
        rows = (
            ("Amount to pay - current month", self._money(summary.earnings_minor), False),
            ("Previous unpaid balance", self._money(summary.previous_unpaid_minor), False),
            ("Advances", self._money(summary.advances_minor), False),
            ("Payments already made", self._money(summary.payments_minor), False),
            ("Remaining due", self._money(summary.remaining_due_minor), True),
        )
        for label, value, strong in rows:
            y = self._draw_row(
                painter,
                content_x,
                y,
                content_w,
                label,
                value,
                height=row_height,
                strong=strong,
            )

        y += height * 0.014

        # Status and carry-forward are payroll-management details and are
        # intentionally omitted from the worker-facing salary slip.
        y += height * 0.022

        # ----------------------------- signatures ---------------------------
        line_y = min(y + height * 0.038, top + height * 0.925)
        line_w = content_w * 0.33
        painter.setPen(QColor("#7B8E9A"))
        painter.drawLine(int(content_x), int(line_y), int(content_x + line_w), int(line_y))
        painter.drawLine(
            int(content_x + content_w - line_w),
            int(line_y),
            int(content_x + content_w),
            int(line_y),
        )
        self._draw_text(
            painter,
            QRectF(content_x, line_y, line_w, height * 0.026),
            "Prepared by",
            size=8,
            color=muted,
            align=Qt.AlignmentFlag.AlignCenter,
        )
        self._draw_text(
            painter,
            QRectF(
                content_x + content_w - line_w,
                line_y,
                line_w,
                height * 0.026,
            ),
            "Worker signature",
            size=8,
            color=muted,
            align=Qt.AlignmentFlag.AlignCenter,
        )

        # ------------------------------- footer -----------------------------
        footer_y = top + height - height * 0.032
        painter.setPen(border)
        painter.drawLine(int(content_x), int(footer_y), int(content_x + content_w), int(footer_y))
        self._draw_text(
            painter,
            QRectF(content_x, footer_y, content_w, height * 0.025),
            "Generated by ChitLog | Local and private finance record",
            size=7,
            color=muted,
            align=Qt.AlignmentFlag.AlignCenter,
        )

    def _render_pdf(
        self,
        output: Path,
        pages: list[tuple[object, object]],
        month: date,
    ) -> None:
        """Render a complete salary-slip PDF to a staging file."""
        writer = QPdfWriter(str(output))
        writer.setTitle(f"ChitLog Salary Slips - {self._month_label(month)}")
        writer.setCreator("ChitLog")
        writer.setResolution(300)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(QPageLayout.Orientation.Portrait)

        # Keep the confirmed Step 15 layout model: zero writer margins and a
        # mathematically centered 12 mm inset calculated from fullRectPixels()
        # inside _draw_worker_page().
        writer.setPageMargins(
            QMarginsF(0, 0, 0, 0),
            QPageLayout.Unit.Millimeter,
        )

        painter = QPainter()
        if not painter.begin(writer):
            raise SalarySlipError("ChitLog could not create the PDF file.")

        try:
            for index, (worker, summary) in enumerate(pages):
                if index:
                    if not writer.newPage():
                        raise SalarySlipError("ChitLog could not add a PDF page.")
                self._draw_worker_page(painter, writer, worker, summary, month)
        finally:
            painter.end()

    @staticmethod
    def _validate_pdf_file(path: Path) -> None:
        try:
            size = path.stat().st_size
            with path.open("rb") as handle:
                header = handle.read(5)
        except OSError:
            raise SalarySlipError(
                "The PDF file could not be validated."
            ) from None

        if size < 1000 or header != b"%PDF-":
            raise SalarySlipError("The PDF file was not created correctly.")

    def generate(
        self,
        output_path: str | Path,
        worker_ids: list[int] | tuple[int, ...],
        month_start: str,
    ) -> int:
        ids = [int(value) for value in worker_ids]
        if not ids:
            raise SalarySlipError(
                "Select at least one worker for the salary slip PDF."
            )

        raw_output = str(output_path)
        if not raw_output or "\x00" in raw_output:
            raise SalarySlipError("Choose a valid PDF output path.")

        output = Path(output_path)
        if output.suffix.lower() != ".pdf":
            output = output.with_suffix(".pdf")

        if output.exists() and (output.is_dir() or output.is_symlink()):
            raise SalarySlipError(
                "Choose a normal PDF file, not a folder or symbolic link."
            )

        try:
            output.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise SalarySlipError(
                "ChitLog could not prepare the selected PDF folder."
            ) from None

        month = self._month_start(month_start)
        pages = []
        for worker_id in ids:
            worker = self.worker_service.get_worker(worker_id)
            if worker is None:
                continue
            summary = self.payroll_service.summary_for_worker(worker_id, month)
            pages.append((worker, summary))

        if not pages:
            raise SalarySlipError(
                "None of the selected workers are available."
            )

        stage = output.with_name(
            f".{output.name}.{uuid4().hex}.part"
        )

        try:
            if stage.exists():
                raise SalarySlipError(
                    "The temporary PDF destination already exists."
                )

            self._render_pdf(stage, pages, month)
            self._validate_pdf_file(stage)

            # Replace the final file only after the complete staged PDF passes
            # validation. A failed render cannot truncate a previous good PDF.
            os.replace(stage, output)
            self._validate_pdf_file(output)
            return len(pages)

        except SalarySlipError:
            stage.unlink(missing_ok=True)
            raise
        except OSError:
            stage.unlink(missing_ok=True)
            raise SalarySlipError(
                "ChitLog could not save the PDF file safely."
            ) from None
        except Exception:
            stage.unlink(missing_ok=True)
            raise SalarySlipError(
                "ChitLog could not create the PDF file safely."
            ) from None
