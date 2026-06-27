"""
Web renderer — serves an HTML form on localhost, opens the browser,
waits for submission, then returns the results.

No external dependencies: uses Python's built-in ``http.server``.
"""
from __future__ import annotations

import html
import json
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer
from typing import Any

from ..base_renderer import FormRenderer
from ..schema import FormField
from ..schema import FormSchema

# ---------------------------------------------------------------------------
# HTML helpers — styled after FinHub (Tailwind CSS, slate palette)
# ---------------------------------------------------------------------------

def _field_html(f: FormField) -> str:
    default = f.resolved_default()
    esc_label = html.escape(f.label)
    name = html.escape(f.name)

    # hint line (min/step/placeholder)
    hints: list[str] = []
    if f.type == "number":
        if f.min is not None:
            hints.append(f"min {f.min:g}")
        if f.step is not None:
            hints.append(f"step {f.step:g}")
    if f.placeholder and (default is None or str(default) != f.placeholder):
        hints.append(html.escape(f.placeholder))
    hint_html = (
        f'<span class="text-[10px] text-slate-400 ml-1 normal-case font-normal">'
        f'({", ".join(hints)})</span>'
        if hints else ""
    )
    opt_badge = (
        '<span class="ml-1 text-[9px] font-bold text-slate-300 bg-slate-100 '
        'px-1.5 py-0.5 rounded-full uppercase">optional</span>'
        if f.optional else
        '<span class="ml-0.5 text-red-400">*</span>'
    )

    label_html = (
        f'<label for="{name}" class="block text-[10px] font-bold text-slate-400 '
        f'uppercase tracking-widest mb-1 ml-1">{esc_label}{opt_badge}{hint_html}</label>'
    )

    input_cls = (
        "w-full px-4 py-3 bg-slate-50 border border-slate-200 rounded-xl "
        "font-medium outline-none focus:ring-2 focus:ring-slate-900 text-sm"
    )

    if f.type == "checkbox":
        checked = "checked" if default else ""
        return f"""<div class="flex items-center space-x-3">
  <input type="checkbox" name="{name}" id="{name}" {checked}
    class="w-4 h-4 accent-slate-900 cursor-pointer">
  <label for="{name}" class="text-sm font-semibold text-slate-700 cursor-pointer select-none">
    {esc_label}{opt_badge}
  </label>
</div>"""

    if f.type == "select":
        opts = "".join(
            f'<option value="{html.escape(str(o))}"'
            + (" selected" if str(o) == str(default) else "")
            + f">{html.escape(str(o))}</option>"
            for o in (f.options or [])
        )
        return f"""<div>
  {label_html}
  <select name="{name}" id="{name}" class="{input_cls}">{opts}</select>
</div>"""

    input_type = "number" if f.type == "number" else "text"
    val = html.escape(str(default)) if default is not None else ""
    placeholder = html.escape(f.placeholder or "")
    extra = ""
    if f.type == "number":
        if f.min is not None:
            extra += f' min="{f.min:g}"'
        if f.step is not None:
            extra += f' step="{f.step:g}"'
    required = "" if f.optional else " required"

    return f"""<div>
  {label_html}
  <input type="{input_type}" name="{name}" id="{name}"
    value="{val}" placeholder="{placeholder}"{extra}{required}
    class="{input_cls}">
</div>"""


def _build_html(schema: FormSchema) -> str:
    fields_html = "\n".join(_field_html(f) for f in schema.fields)
    title = html.escape(schema.title)
    # Initials from first two words (e.g. "CJTrade OneShot" → "CJ")
    words = schema.title.split()
    initials = (words[0][0] + words[1][0]).upper() if len(words) >= 2 else words[0][:2].upper()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#f8fafc] min-h-screen flex items-center justify-center p-6">
  <div class="bg-white p-10 rounded-3xl border border-slate-200 shadow-2xl w-full max-w-lg">

    <div class="flex flex-col items-center mb-8">
      <div class="w-12 h-12 bg-slate-900 rounded-2xl flex items-center justify-center
                  text-white font-bold text-xl mb-4 shadow-lg">{initials}</div>
      <h2 class="text-2xl font-black text-slate-900">{title}</h2>
    </div>

    <form id="main-form" method="POST" action="/submit" class="space-y-4">
      {fields_html}

      <button type="submit"
        class="w-full bg-slate-900 text-white font-bold py-4 rounded-2xl mt-2
               hover:bg-slate-800 transition-all shadow-lg text-sm tracking-wide uppercase">
        ▶ Run
      </button>
    </form>

  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    schema: FormSchema
    result_box: list  # shared container; filled on POST

    def log_message(self, fmt, *args):  # suppress request logs
        pass

    def do_GET(self):
        page = _build_html(self.schema).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        raw = urllib.parse.parse_qs(body, keep_blank_values=True)

        result: dict[str, Any] = {}
        for f in self.schema.fields:
            if f.type == "checkbox":
                result[f.name] = f.name in raw
            else:
                vals = raw.get(f.name, [None])
                raw_val = vals[0] if vals else None
                if not raw_val:
                    result[f.name] = f.resolved_default()
                else:
                    try:
                        result[f.name] = f.coerce(raw_val)
                    except ValueError:
                        result[f.name] = f.resolved_default()

        self.result_box.append(result)

        done_page = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Done</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#f8fafc] min-h-screen flex items-center justify-center p-6">
  <div class="bg-white p-10 rounded-3xl border border-slate-200 shadow-2xl w-full max-w-sm text-center">
    <div class="w-14 h-14 bg-emerald-50 rounded-2xl flex items-center justify-center mx-auto mb-6">
      <svg class="w-7 h-7 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7"/>
      </svg>
    </div>
    <h2 class="text-2xl font-black text-slate-900 mb-2">Submitted</h2>
    <p class="text-sm text-slate-400 font-medium">You can close this tab now.</p>
  </div>
</body>
</html>""".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(done_page)))
        self.end_headers()
        self.wfile.write(done_page)


# ---------------------------------------------------------------------------
# WebRenderer
# ---------------------------------------------------------------------------

class WebRenderer(FormRenderer):
    """
    Renders the form as a local HTML page.

    Starts a one-shot HTTP server on ``localhost:{port}`` (default 9876),
    opens the browser, waits for the form to be submitted, then shuts down.
    """

    def __init__(self, port: int = 9876, auto_open: bool = True) -> None:
        self.port = port
        self.auto_open = auto_open

    def render(self, schema: FormSchema) -> dict[str, Any]:
        result_box: list = []

        # Patch class-level attributes used by the handler
        class Handler(_Handler):
            pass
        Handler.schema = schema
        Handler.result_box = result_box

        server = HTTPServer(("127.0.0.1", self.port), Handler)
        url = f"http://127.0.0.1:{self.port}"
        print(f"  Form available at {url}", file=sys.stderr)

        # Run server in background thread; stop after first POST
        def _serve():
            while not result_box:
                server.handle_request()
            server.server_close()

        t = threading.Thread(target=_serve, daemon=True)
        t.start()

        if self.auto_open:
            webbrowser.open(url)

        t.join()
        return result_box[0]
