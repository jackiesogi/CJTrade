# Editor bundle

`static/vendor/codemirror.bundle.js` is a build artifact. This directory is its
input, committed so the artifact is not a 460 KB blob nobody can regenerate.

```sh
cd tools/editor
npm install
npm run build      # rebuild static/vendor/codemirror.bundle.js
npm run verify     # drive the built bundle in jsdom
```

`verify.mjs` loads the *built* artifact the page loads, in a real DOM, and
checks the contract `app.js` depends on: that `window.FinHubEditor` appears,
that an editor mounts with gutters and Python highlighting, that text
round-trips, that a server diagnostic lands on a line and an out-of-range line
is clamped rather than thrown, and that our completion source is registered
*alongside* the Python language's own rather than replacing it. Run it after
any change to `entry.js`; it is the only thing standing between a broken
bundle and a blank editor in the browser.

## Why vendored rather than loaded from a CDN

Tailwind and Chart.js do come from CDNs in `templates/index.html`, so this is
inconsistent on purpose. The editor is where somebody writes the code that
places orders: a page that cannot load its editor offline, or that silently
takes a new CodeMirror release mid-session, is a worse trade here than 460 KB
in the repository.

## Why CodeMirror and not Monaco

Monaco is the editor out of VS Code and looks the part. Two things decided it
the other way:

1. **Completion composes.** Our API is a small closed set, so the valuable tier
   is a generated completion list rather than a language server. CodeMirror
   registers ours as an *additional* source on the Python language, so
   `@codemirror/lang-python`'s own global and local-scope completion keeps
   working alongside it — that is what completes the user's own variables.
   Monaco's `registerCompletionItemProvider` *replaces* the built-in list when
   a provider returns anything (microsoft/monaco-editor#1036), so we would have
   had to rebuild the built-ins ourselves.
2. **No bundler needed in the app.** Monaco wants an AMD loader and worker
   setup; FinHub serves Jinja templates and three plain script files. One
   vendored IIFE fits that, and `window.FinHubEditor` is the entire surface
   `app.js` sees.

If full Pyright-grade intelligence is ever wanted, both can do it — Monaco's
path is smoother, but CodeMirror LSP clients ship in production (Val Town,
marimo), so this is not a dead end.

## What the bundle exposes

```js
window.FinHubEditor = {
    create(parent, doc, onChange) -> view,
    getValue(view) -> string,
    setValue(view, text),
    showDiagnostics(view, [{line, offset, severity, message}]),
    setApi(entries),          // from GET /api/v1/strategies/api-reference
    setReadOnly(view, flag),
}
```
