import threading
import time
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright, Page, Response, Error
from loki.engine.browser import launch_browser, normalize_browser_name
from loki.engine.detectors import Detector, capture_dom_snapshot, default_detectors
from loki.engine.devices import resolve_device, suggest_device_names
from loki.models import IncidentReport
from loki.personas.base import BasePersona


class ChaosSandbox:
    """Manages an isolated browser session with live error sniffing and video capture."""

    def __init__(self, output_dir: str = ".loki/runs", headless: bool = True, browser_name: str = "chromium", seed: int | None = None):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        self.browser_name = normalize_browser_name(browser_name)
        self.seed = seed

    def _context_options(self, device_config: dict | None, har_file: Path) -> dict[str, Any]:
        """Browser context with video + HAR recording, emulating the device if one was resolved."""
        options: dict[str, Any] = {
            "record_video_dir": str(self.output_dir / "videos"),
            "record_har_path": str(har_file),
        }
        if device_config:
            options.update(device_config)
            if "viewport" in device_config:
                options["record_video_size"] = device_config["viewport"]
        else:
            options["record_video_size"] = {"width": 1280, "height": 720}
        return options

    @staticmethod
    def _drive(
        page: Page,
        report: IncidentReport,
        persona: BasePersona | None,
        journey_data: dict | None,
        duration: int,
    ) -> list[dict[str, Any]]:
        """Runs the guided journey or the persona's free-form attack; returns the replay trace."""
        trace: list[dict[str, Any]] = []
        if journey_data and journey_data.get("steps"):
            report.actions_taken.append(f"Started guided journey: '{journey_data.get('name')}'")
            for step in journey_data["steps"]:
                if persona:
                    persona.attack_step(page=page, step=step)
                    trace.extend(persona.trace)
                    persona.trace.clear()
                else:
                    selector = step.get("selector")
                    if step.get("action") == "click" and selector:
                        page.click(selector, timeout=2000)
                        trace.append({"kind": "click", "selector": selector})
                    elif step.get("action") == "input" and selector:
                        value = step.get("value", "")
                        page.fill(selector, value)
                        trace.append({"kind": "fill", "selector": selector, "value": value})
                time.sleep(0.2)

            if persona:
                report.actions_taken.extend(persona.actions_log)
        elif persona:
            persona.attack(page=page, duration=duration)
            report.actions_taken = persona.actions_log
            trace.extend(persona.trace)
        else:
            time.sleep(duration)
        return trace

    def run_session(
        self,
        target_url: str,
        duration: int = 5,
        persona: BasePersona | None = None,
        journey_data: dict | None = None,
        device_name: str | None = None,
        orientation: str = "portrait",
        detectors: list[Detector] | None = None,
    ) -> IncidentReport:
        """Launches the target URL, applies chaotic attacks, and records evidence."""
        effective_seed = self.seed if self.seed is not None else (getattr(persona, "seed", None) if persona else None)
        report = IncidentReport(
            target_url=target_url,
            persona_name=persona.name if persona else None,
            orientation=orientation,
            browser_name=self.browser_name,
            seed=effective_seed,
        )
        if detectors is None:
            detectors = default_detectors(persona)
        start_time = time.time()
        temp_har_file = self.output_dir / f"temp_network_{int(start_time)}.har"

        with sync_playwright() as p:
            report.device_requested = device_name
            report.device_name, device_config = resolve_device(
                device_name=device_name,
                orientation=orientation,
                devices=p.devices,
            )
            if device_name and not report.device_name:
                report.device_suggestions = suggest_device_names(device_name, p.devices)

            browser = launch_browser(p, self.browser_name, self.headless)
            context = browser.new_context(**self._context_options(device_config, temp_har_file))
            page: Page = context.new_page()
            for detector in detectors:
                detector.attach(page, report)

            try:
                nav_res = page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                if nav_res and nav_res.status >= 400:
                    suffix = f" ({nav_res.status_text})" if nav_res.status_text else ""
                    report.navigation_errors.append(
                        f"Initial navigation returned HTTP {nav_res.status}{suffix}: {page.url}"
                    )
                for detector in detectors:
                    detector.after_navigation(page, report)

                report.replay_trace = self._drive(page, report, persona, journey_data, duration)
                if persona and hasattr(persona, "get_api_faults"):
                    report.api_faults = persona.get_api_faults()

            except Error as e:
                report.crashes.append(f"Navigation error: {str(e)}")
            finally:
                if not page.is_closed():
                    for detector in detectors:
                        try:
                            detector.inspect(page, report)
                        except Exception:
                            pass
                    try:
                        report.dom_snapshot = capture_dom_snapshot(page)
                    except Exception:
                        pass

                page.close()
                video_obj = page.video
                context.close()
                browser.close()

                if video_obj:
                    report.video_path = video_obj.path()
                if temp_har_file.exists():
                    report.har_path = str(temp_har_file)

        report.duration_seconds = round(time.time() - start_time, 2)
        return report

    def _run_concurrency_lane(
        self,
        lane: int,
        barrier: threading.Barrier,
        target_url: str,
        selector: str | None,
        device_config: dict | None,
        settle_seconds: float,
        results: list[dict[str, Any]],
        results_lock: threading.Lock,
    ):
        """Runs one isolated browser lane: navigate, wait for every other lane to be
        ready, then fire the target click at (as close as possible to) the same
        instant as all other lanes, and record what happened.

        Each lane gets its own Playwright connection and browser process — the sync
        Playwright API has thread affinity, so true concurrent requests require
        independent browsers driven from independent threads, not one shared page.
        """
        lane_result: dict[str, Any] = {
            "lane": lane, "selector": selector, "crashes": [], "responses": [], "final_text": None,
        }
        try:
            with sync_playwright() as p:
                browser = launch_browser(p, self.browser_name, self.headless)
                context = browser.new_context(**(device_config or {}))
                page = context.new_page()

                page.on("pageerror", lambda err: lane_result["crashes"].append(str(err)))
                page.on(
                    "console",
                    lambda msg: lane_result["crashes"].append(f"Console error: {msg.text}")
                    if msg.type == "error"
                    else None,
                )

                def handle_response(response: Response):
                    try:
                        if response.request.method in ("POST", "PUT", "PATCH", "DELETE") or response.status >= 400:
                            lane_result["responses"].append({
                                "url": response.url, "status": response.status, "method": response.request.method,
                            })
                    except Exception:
                        pass

                page.on("response", handle_response)

                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                except Error as e:
                    lane_result["crashes"].append(f"Navigation error: {str(e)}")

                lane_selector = selector
                if not lane_selector:
                    try:
                        el = page.query_selector("button:visible, input[type='submit']:visible")
                        lane_selector = BasePersona.resilient_selector(el) if el else None
                    except Exception:
                        lane_selector = None
                lane_result["selector"] = lane_selector

                # Rendezvous: every lane blocks here until all lanes have loaded the
                # page and resolved their target selector, then all proceed together.
                try:
                    barrier.wait(timeout=15)
                except threading.BrokenBarrierError:
                    lane_result["crashes"].append("Lane did not reach the synchronized click in time (barrier timeout).")

                if lane_selector:
                    try:
                        page.click(lane_selector, timeout=2000, force=True, no_wait_after=True)
                    except Exception as e:
                        lane_result["crashes"].append(f"Synchronized click failed: {str(e)}")
                else:
                    lane_result["crashes"].append("No clickable target element found for this lane.")

                page.wait_for_timeout(int(settle_seconds * 1000))
                try:
                    status_el = page.query_selector("#status-box, .status, [role='alert'], .alert")
                    if status_el:
                        lane_result["final_text"] = (status_el.inner_text() or "").strip()
                except Exception:
                    pass

                context.close()
                browser.close()
        except Exception as e:
            lane_result["crashes"].append(f"Lane fatal error: {str(e)}")

        with results_lock:
            results.append(lane_result)

    def run_concurrent_probe(
        self,
        target_url: str,
        concurrency: int,
        selector: str | None = None,
        device_name: str | None = None,
        orientation: str = "portrait",
        settle_seconds: float = 2.0,
    ) -> IncidentReport:
        """Opens `concurrency` independent browser lanes against the same URL and fires
        the same click on all of them in lockstep, to probe for server-side race
        conditions (double charges, oversold inventory, duplicate submissions) that a
        single tab's sequential click bursts cannot trigger."""
        report = IncidentReport(
            target_url=target_url,
            persona_name=None,
            orientation=orientation,
            concurrency=concurrency,
            browser_name=self.browser_name,
            seed=self.seed,
        )
        start_time = time.time()

        with sync_playwright() as p:
            resolved_device_name, device_config = resolve_device(device_name=device_name, orientation=orientation, devices=p.devices)
            report.device_requested = device_name
            report.device_name = resolved_device_name

        barrier = threading.Barrier(concurrency)
        results: list[dict[str, Any]] = []
        results_lock = threading.Lock()
        threads = [
            threading.Thread(
                target=self._run_concurrency_lane,
                args=(i, barrier, target_url, selector, device_config, settle_seconds, results, results_lock),
                name=f"loki-concurrency-lane-{i}",
            )
            for i in range(concurrency)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        results.sort(key=lambda r: r["lane"])
        report.concurrency_lanes = results

        success_responses = 0
        for lane in results:
            for c in lane["crashes"]:
                report.crashes.append(f"[lane {lane['lane']}] {c}")
            for r in lane["responses"]:
                if r["status"] >= 400:
                    report.http_errors.append(f"[lane {lane['lane']}] HTTP {r['status']} on {r['url']}")
                elif r["status"] < 400:
                    success_responses += 1
            selector_desc = lane["selector"] or "no target element"
            status_desc = f", final state: '{lane['final_text']}'" if lane["final_text"] else ""
            report.actions_taken.append(
                f"Lane {lane['lane']}: synchronized click on '{selector_desc}' "
                f"({len(lane['responses'])} tracked responses{status_desc})"
            )

        if success_responses > 1:
            report.actions_taken.append(
                f"⚠ {success_responses} lanes recorded a successful (< 400) response for the same "
                f"synchronized action — inspect for missing server-side idempotency locks."
            )

        report.duration_seconds = round(time.time() - start_time, 2)
        return report
