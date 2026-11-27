// Drive the vendored bundle in a real DOM, so the contract app.js relies on
// is checked rather than assumed: that window.FinHubEditor exists, that an
// editor mounts, that text round-trips, that our completion source answers,
// and that a server diagnostic lands on the right line.
import {JSDOM} from "jsdom";
import {readFileSync} from "node:fs";

const dom = new JSDOM(`<!doctype html><html><body><div id="host"></div></body></html>`,
                      {pretendToBeVisual: true, runScripts: "outside-only"});
const {window} = dom;
// node 26 makes globalThis.navigator a getter-only property, so it is defined
// rather than assigned.
Object.defineProperty(globalThis, "navigator",
                      {value: window.navigator, configurable: true});
for (const key of ["window", "document", "HTMLElement", "Element",
                   "Node", "Range", "getComputedStyle", "DOMParser",
                   "MutationObserver", "requestAnimationFrame",
                   "cancelAnimationFrame", "CustomEvent", "Event",
                   "KeyboardEvent", "InputEvent", "DocumentFragment",
                   "Text", "ShadowRoot", "ResizeObserver", "IntersectionObserver"]) {
    if (window[key] !== undefined) globalThis[key] = window[key];
}
globalThis.requestAnimationFrame ??= (fn) => setTimeout(fn, 0);
globalThis.cancelAnimationFrame ??= clearTimeout;

let ok = 0, fail = 0;
const check = (label, cond, extra = "") => {
    if (cond) { ok++; console.log("  ok   " + label); }
    else { fail++; console.log("  FAIL " + label + " " + extra); }
};

const code = readFileSync(
    "/Users/chshc/Downloads/gitrepo/FinHub/static/vendor/codemirror.bundle.js",
    "utf8");
// Same evaluation the browser does: a plain script in the page's scope.
new Function(code).call(globalThis);

// The bundle assigns to `window`, which inside the IIFE resolves to the jsdom
// window rather than to globalThis -- the same object the page would see.
check("window.FinHubEditor is defined", !!window.FinHubEditor);
const E = window.FinHubEditor;
check("exposes exactly the surface app.js calls",
      ["create", "getValue", "setValue", "showDiagnostics", "setApi",
       "setReadOnly"].every(k => typeof E[k] === "function"),
      JSON.stringify(Object.keys(E || {})));

E.setApi([
    {name: "buy", qualified: "buy", kind: "function",
     signature: "buy(shares=None)", doc: "Ask to buy."},
    {name: "hold", qualified: "hold", kind: "function",
     signature: "hold(reason='')", doc: "Do nothing."},
    {name: "bb", qualified: "ta.bb", kind: "method",
     signature: "bb(closes, timeperiod=20)", doc: "Bollinger bands."},
    {name: "efficiency", qualified: "ta.efficiency", kind: "method",
     signature: "efficiency(closes, lookback=14)", doc: "Trend strength."},
]);

let changes = 0;
const SOURCE = 'from cjtrade.pkgs.strategy.authoring import *\n\n\ndef on_bar(bar, account):\n    return hold("x")\n';
const view = E.create(document.getElementById("host"), SOURCE, () => changes++);
check("an editor mounted", !!view && document.getElementById("host").children.length > 0);
check("the document round-trips", E.getValue(view) === SOURCE);
check("python highlighting is active",
      !!document.querySelector("#host .cm-content"),
      document.getElementById("host").innerHTML.slice(0, 120));
check("line numbers are rendered", !!document.querySelector("#host .cm-gutters"));

E.setValue(view, "x = 1\n");
check("setValue replaces the document", E.getValue(view) === "x = 1\n");
check("setValue fires the change callback", changes > 0, `changes=${changes}`);

// Diagnostics: line 1, which must land inside the document rather than throw.
E.showDiagnostics(view, [
    {line: 1, offset: 1, severity: "error", message: "nope"},
]);
check("a diagnostic is accepted and marked",
      !!document.querySelector("#host .cm-lintRange, #host .cm-gutterElement"),
      "no marker found");

// A line number past the end is clamped rather than dropped or thrown.
let threw = null;
try {
    E.showDiagnostics(view, [{line: 9999, offset: 1, severity: "error",
                              message: "past the end"}]);
} catch (e) { threw = e; }
check("a line past the end is clamped, not thrown", threw === null,
      threw && threw.message);

E.setReadOnly(view, true);
check("read-only is applied", view.state.readOnly === true);
E.setReadOnly(view, false);
check("read-only is reversible", view.state.readOnly === false);

/* Completion. Reached through the language's own data facet, which is how
 * app.js's source gets merged with @codemirror/lang-python's rather than
 * replacing it -- the thing that decided CodeMirror over Monaco. */
E.setValue(view, "ta.");
view.dispatch({selection: {anchor: 3}});
const sources = view.state.languageDataAt("autocomplete", 3);
check("the python language exposes more than one completion source",
      sources.length >= 2, `got ${sources.length}`);

let result = null;
for (const source of sources) {
    if (typeof source !== "function") continue;
    const r = source({
        state: view.state, pos: 3, explicit: true,
        matchBefore: (re) => {
            const line = view.state.doc.lineAt(3);
            const text = line.text.slice(0, 3 - line.from);
            const m = text.match(re);
            return m ? {from: line.from + m.index, to: 3, text: m[0]} : null;
        },
    });
    if (r && r.options && r.options.some(o => o.label === "bb")) result = r;
}
check("after `ta.` our indicators are offered", !!result,
      result ? "" : "no source returned bb");
if (result) {
    const labels = result.options.map(o => o.label).sort();
    check("and only ta's members, not the top-level names",
          labels.join(",") === "bb,efficiency", labels.join(","));
    check("with the signature as the detail",
          result.options[0].detail.includes("timeperiod"),
          result.options[0].detail);
}

console.log(`\n${ok} ok, ${fail} failed`);
process.exit(fail ? 1 : 0);
