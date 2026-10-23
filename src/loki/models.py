from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncidentReport:
    """Stores all anomalies and crash data captured during an execution."""
    target_url: str
    persona_name: str | None = None
    browser_name: str = "chromium"
    seed: int | None = None
    device_name: str | None = None
    device_requested: str | None = None
    device_suggestions: list[str] = field(default_factory=list)
    orientation: str = "portrait"
    crashes: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    http_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    unhandled_rejections: list[str] = field(default_factory=list)
    navigation_errors: list[str] = field(default_factory=list)
    resource_failures: list[str] = field(default_factory=list)
    unexpected_dialogs: list[str] = field(default_factory=list)
    layout_issues: list[str] = field(default_factory=list)
    actions_taken: list[str] = field(default_factory=list)
    replay_trace: list[dict[str, Any]] = field(default_factory=list)
    video_path: str | None = None
    har_path: str | None = None
    dom_snapshot: str | None = None
    duration_seconds: float = 0.0
    # Multi-tab concurrency probe: `concurrency` independent browser lanes are
    # synchronized to fire the same action at (as close as possible to) the same
    # instant, to catch server-side race conditions single-tab click bursts cannot
    # (a single page's JS event handlers never truly run concurrently).
    concurrency: int = 1
    concurrency_lanes: list[dict[str, Any]] = field(default_factory=list)
    api_faults: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_crashes(self) -> bool:
        """Returns True if any unhandled error, console error, HTTP failure, or anomaly occurred."""
        return (
            len(self.crashes) > 0
            or len(self.console_errors) > 0
            or len(self.http_errors) > 0
            or len(self.failed_requests) > 0
            or len(self.unhandled_rejections) > 0
            or len(self.navigation_errors) > 0
            or len(self.resource_failures) > 0
            or len(self.unexpected_dialogs) > 0
        )

    @property
    def has_failures(self) -> bool:
        """Alias for has_crashes indicating whether any failure condition was detected."""
        return self.has_crashes

    @property
    def total_failures_count(self) -> int:
        """Total count of failure instances detected across all vectors."""
        return (
            len(set(self.crashes))
            + len(set(self.console_errors))
            + len(self.http_errors)
            + len(self.failed_requests)
            + len(self.unhandled_rejections)
            + len(self.navigation_errors)
            + len(self.resource_failures)
            + len(self.unexpected_dialogs)
        )

    @property
    def has_layout_issues(self) -> bool:
        """Returns True if any mobile responsive layout violation occurred."""
        return len(self.layout_issues) > 0
