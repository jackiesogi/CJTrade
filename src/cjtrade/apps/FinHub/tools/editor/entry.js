// FinHub's CodeMirror bundle.
//
// Built once with esbuild and vendored into static/vendor/, rather than
// imported from a CDN at run time. Tailwind and Chart.js do come from CDNs in
// this app, but this editor is where someone writes the code that places
// orders, and a page that cannot load its editor offline -- or that loads a
// version nobody pinned -- is a worse trade here than the extra 300 KB.
//
// Everything the page needs hangs off window.FinHubEditor. Keeping the surface
// this narrow is deliberate: app.js stays plain ES5-ish script with no module
// loader, exactly like the rest of static/.
import {EditorView, keymap, lineNumbers, highlightActiveLine,
        highlightActiveLineGutter, highlightSpecialChars, drawSelection,
        rectangularSelection, crosshairCursor, dropCursor} from "@codemirror/view";
import {EditorState, Compartment} from "@codemirror/state";
import {defaultKeymap, history, historyKeymap, indentWithTab} from "@codemirror/commands";
import {searchKeymap, highlightSelectionMatches} from "@codemirror/search";
import {python, pythonLanguage} from "@codemirror/lang-python";
import {autocompletion, completionKeymap, closeBrackets,
        closeBracketsKeymap} from "@codemirror/autocomplete";
import {syntaxHighlighting, defaultHighlightStyle, indentOnInput,
        bracketMatching, foldGutter, foldKeymap} from "@codemirror/language";
import {lintKeymap, linter, lintGutter, setDiagnostics} from "@codemirror/lint";

// The API the user may call, fetched from FinHub (which gets it from
// strategy-tool, which generates it by introspecting the authoring module).
// Stored here so the completion source can stay synchronous.
let API = [];

function iconFor(kind) {
    if (kind === "function" || kind === "method") return "function";
    if (kind === "class") return "class";
    if (kind === "namespace" || kind === "module") return "namespace";
    if (kind === "property" || kind === "field") return "property";
    return "variable";
}

/* Completion over our own API.
 *
 * Registered as an extra source on the Python language rather than as a
 * replacement, so @codemirror/lang-python's own global and local-scope
 * completion keeps working -- that is what completes the user's own
 * variables, which a static list of our names cannot. Monaco would have
 * replaced the built-in list here instead of merging with it. */
function apiCompletions(context) {
    // After a dot: only the members of that owner, so `ta.` offers the nine
    // indicators and nothing else.
    const dotted = context.matchBefore(/([A-Za-z_][\w]*)\.(\w*)$/);
    if (dotted) {
        const owner = dotted.text.split(".")[0];
        const members = API.filter(e => e.qualified.startsWith(owner + "."));
        if (!members.length) return null;
        return {
            from: dotted.from + owner.length + 1,
            options: members.map(e => ({
                label: e.name,
                type: iconFor(e.kind),
                detail: e.signature,
                info: e.doc || undefined,
            })),
            validFor: /^\w*$/,
        };
    }

    const word = context.matchBefore(/[A-Za-z_][\w]*$/);
    if (!word && !context.explicit) return null;
    const top = API.filter(e => !e.qualified.includes("."));
    return {
        from: word ? word.from : context.pos,
        options: top.map(e => ({
            label: e.name,
            type: iconFor(e.kind),
            detail: e.signature,
            info: e.doc || undefined,
        })),
        validFor: /^\w*$/,
    };
}

const readOnly = new Compartment();

function create(parent, doc, onChange) {
    const view = new EditorView({
        parent,
        state: EditorState.create({
            doc: doc || "",
            extensions: [
                lineNumbers(),
                highlightActiveLineGutter(),
                highlightSpecialChars(),
                history(),
                foldGutter(),
                drawSelection(),
                dropCursor(),
                EditorState.allowMultipleSelections.of(true),
                indentOnInput(),
                syntaxHighlighting(defaultHighlightStyle, {fallback: true}),
                bracketMatching(),
                closeBrackets(),
                autocompletion(),
                rectangularSelection(),
                crosshairCursor(),
                highlightActiveLine(),
                highlightSelectionMatches(),
                lintGutter(),
                keymap.of([
                    ...closeBracketsKeymap,
                    ...defaultKeymap,
                    ...searchKeymap,
                    ...historyKeymap,
                    ...foldKeymap,
                    ...completionKeymap,
                    ...lintKeymap,
                    indentWithTab,
                ]),
                python(),
                // Our names, merged with the language's own sources.
                pythonLanguage.data.of({autocomplete: apiCompletions}),
                readOnly.of(EditorState.readOnly.of(false)),
                EditorView.updateListener.of(update => {
                    if (update.docChanged && onChange) onChange();
                }),
                EditorView.theme({
                    "&": {fontSize: "13px", height: "100%"},
                    ".cm-scroller": {
                        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
                        lineHeight: "1.6",
                    },
                    "&.cm-focused": {outline: "none"},
                    ".cm-gutters": {
                        backgroundColor: "#f8fafc",
                        border: "none",
                        color: "#94a3b8",
                    },
                    ".cm-activeLine": {backgroundColor: "#f8fafc"},
                    ".cm-activeLineGutter": {backgroundColor: "#f1f5f9"},
                }),
            ],
        }),
    });
    return view;
}

function getValue(view) {
    return view.state.doc.toString();
}

function setValue(view, text) {
    view.dispatch({
        changes: {from: 0, to: view.state.doc.length, insert: text || ""},
    });
}

/* Server-side diagnostics, placed on the right lines.
 *
 * `line` and `offset` come from strategy-tool as 1-based, which is how Python
 * reports them; CodeMirror wants document offsets. A line number past the end
 * of the document is clamped rather than dropped -- it happens when the user
 * edits after a check was requested, and losing the message would be worse
 * than showing it on the last line. */
function showDiagnostics(view, diagnostics) {
    const doc = view.state.doc;
    const marks = (diagnostics || []).map(d => {
        const lineNo = Math.max(1, Math.min(doc.lines, d.line || 1));
        const line = doc.line(lineNo);
        const from = Math.min(line.to, line.from + Math.max(0, (d.offset || 1) - 1));
        return {
            from,
            to: line.to > from ? line.to : from + 1,
            severity: d.severity === "warning" ? "warning" : "error",
            message: d.message,
        };
    });
    view.dispatch(setDiagnostics(view.state, marks));
}

function setApi(entries) {
    API = Array.isArray(entries) ? entries : [];
}

function setReadOnly(view, flag) {
    view.dispatch({
        effects: readOnly.reconfigure(EditorState.readOnly.of(!!flag)),
    });
}

window.FinHubEditor = {
    create, getValue, setValue, showDiagnostics, setApi, setReadOnly,
};
