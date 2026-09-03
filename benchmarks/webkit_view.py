#!/usr/bin/env python3
"""Minimal continuously visible GTK 3 WebKitGTK benchmark host."""

import json
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import GLib, Gtk, WebKit2  # noqa: E402


def main():
    url = sys.argv[1]
    window = Gtk.Window(title="MPPT memory benchmark")
    window.set_default_size(1280, 800)
    manager = WebKit2.UserContentManager()
    manager.add_script(WebKit2.UserScript(
        """
        window.__mpptBenchmark = {active: 0, maxActive: 0, completed: 0, overlapEvents: 0};
        const originalFetch = window.fetch;
        window.fetch = function(...args) {
          const url = String(args[0] && args[0].url ? args[0].url : args[0]);
          if (!url.includes('_dash-update-component')) {
            return originalFetch.apply(this, args);
          }
          const state = window.__mpptBenchmark;
          state.active++; state.maxActive = Math.max(state.maxActive, state.active);
          if (state.active > 1) state.overlapEvents++;
          return originalFetch.apply(this, args).finally(() => {
            state.active--; state.completed++;
          });
        };
        const originalOpen = XMLHttpRequest.prototype.open;
        XMLHttpRequest.prototype.open = function(method, url, ...args) {
          this.__mpptIsUpdate = String(url).includes('_dash-update-component');
          return originalOpen.call(this, method, url, ...args);
        };
        const originalSend = XMLHttpRequest.prototype.send;
        XMLHttpRequest.prototype.send = function(...args) {
          if (!this.__mpptIsUpdate) return originalSend.apply(this, args);
          const state = window.__mpptBenchmark;
          state.active++; state.maxActive = Math.max(state.maxActive, state.active);
          if (state.active > 1) state.overlapEvents++;
          this.addEventListener('loadend', () => { state.active--; state.completed++; }, {once: true});
          return originalSend.apply(this, args);
        };
        """,
        WebKit2.UserContentInjectedFrames.ALL_FRAMES,
        WebKit2.UserScriptInjectionTime.START,
        None,
        None,
    ))
    view = WebKit2.WebView.new_with_user_content_manager(manager)
    window.add(view)
    window.connect("destroy", Gtk.main_quit)
    view.get_settings().set_property("enable-developer-extras", True)

    def load_changed(_view, event):
        if event == WebKit2.LoadEvent.FINISHED:
            print(json.dumps({"event": "loaded"}), flush=True)

    def crashed(*_args):
        print(json.dumps({"event": "web-process-terminated"}), flush=True)
        return False

    view.connect("load-changed", load_changed)
    view.connect("web-process-terminated", crashed)

    def execute_probe(request_id):
        script = """
        (() => {
          const root = document.getElementById('g3');
          const child = root && root.querySelector('.js-plotly-plot');
          const graph = child || root;
          if (!graph || !graph.data) return {ready: false, lengths: []};
          const callbacks = performance.getEntriesByType('resource')
            .filter(e => e.name.includes('_dash-update-component'));
          return {
            ready: true,
            lengths: graph.data.map(t => (t.x || []).length),
            completed_callbacks: callbacks.length,
            observed_requests: window.__mpptBenchmark
              ? window.__mpptBenchmark.completed : callbacks.length,
            active_requests: window.__mpptBenchmark
              ? window.__mpptBenchmark.active : 0,
            max_active_requests: window.__mpptBenchmark
              ? window.__mpptBenchmark.maxActive : 0,
            overlap_events: window.__mpptBenchmark
              ? window.__mpptBenchmark.overlapEvents : 0,
            last_callback_end_ms: callbacks.length
              ? callbacks[callbacks.length - 1].responseEnd : 0
          };
        })()
        """

        def finished(webview, result, _data):
            try:
                value = webview.run_javascript_finish(result).get_js_value().to_json(0)
                response = {"event": "probe", "id": request_id, "result": json.loads(value)}
            except Exception as error:
                response = {"event": "probe", "id": request_id, "error": str(error)}
            print(json.dumps(response), flush=True)

        view.run_javascript(script, None, finished, None)
        return False

    def reset_metrics():
        view.run_javascript(
            "window.__mpptBenchmark = {active: 0, maxActive: 0, completed: 0, overlapEvents: 0};",
            None,
            None,
            None,
        )
        return False

    def read_commands():
        for line in sys.stdin:
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                continue
            if command.get("command") == "probe":
                GLib.idle_add(execute_probe, command.get("id"))
            elif command.get("command") == "reset-metrics":
                GLib.idle_add(reset_metrics)
            elif command.get("command") == "quit":
                GLib.idle_add(Gtk.main_quit)

    threading.Thread(target=read_commands, daemon=True).start()
    window.show_all()
    view.load_uri(url)
    Gtk.main()


if __name__ == "__main__":
    main()
