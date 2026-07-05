/**
 * Trickcal Revive — 运行时韩文抓取（Frida）
 *
 * 用法（AIVM adb 已连接，如 127.0.0.1:8555）:
 *   1. 先在本机运行 capture_server.py
 *   2. adb forward tcp:8787 tcp:8787
 *   3. frida -U -f com.epidgames.trickcalrevive -l hook_capture_ko.js --no-pause
 *
 * 或 attach 已运行进程:
 *   frida -U com.epidgames.trickcalrevive -l hook_capture_ko.js
 */
'use strict';

const PKG = 'com.epidgames.trickcalrevive';
const CAPTURE_URL = 'http://127.0.0.1:8787/capture';
const MIN_LEN = 2;
const MAX_LEN = 800;
const SEEN = {};
const MAX_SEEN = 12000;

function log(msg) {
    console.log('[ko-capture] ' + msg);
}

function hasHangul(s) {
    return /[\uAC00-\uD7AF]/.test(s);
}

function shouldCapture(s) {
    if (!s || s.length < MIN_LEN || s.length > MAX_LEN) return false;
    if (!hasHangul(s)) return false;
    const han = (s.match(/[\uAC00-\uD7AF]/g) || []).length;
    if (han < Math.min(2, s.length * 0.3)) return false;
    return true;
}

function remember(s) {
    if (SEEN[s]) return false;
    SEEN[s] = 1;
    const keys = Object.keys(SEEN);
    if (keys.length > MAX_SEEN) {
        delete SEEN[keys[0]];
    }
    return true;
}

function postCapture(text, source) {
    if (!remember(text)) return;
    log('[' + source + '] ' + text.substring(0, 120));
    send({ type: 'ko', text: text, source: source });
    if (!Java.available) return;
    Java.scheduleOnMainThread(function () {
        try {
            const body = JSON.stringify({ text: text, source: source, pkg: PKG });
            const URL = Java.use('java.net.URL');
            const url = URL.$new(CAPTURE_URL);
            const conn = url.openConnection();
            conn.setRequestMethod('POST');
            conn.setRequestProperty('Content-Type', 'application/json; charset=utf-8');
            conn.setDoOutput(true);
            const os = conn.getOutputStream();
            const bytes = Java.use('java.lang.String').$new(body).getBytes('UTF-8');
            os.write(bytes);
            os.flush();
            os.close();
            conn.getInputStream().close();
        } catch (e) {
            /* capture_server 未启动时忽略 */
        }
    });
}

function readIl2CppString(ptr) {
    if (!ptr || ptr.isNull()) return null;
    try {
        const len = ptr.add(0x10).readInt32();
        if (len <= 0 || len > MAX_LEN) return null;
        return ptr.add(0x14).readUtf16String(len);
    } catch (_) {
        return null;
    }
}

function tryReadStringArg(arg) {
    if (!arg || arg.isNull()) return null;
    let s = readIl2CppString(arg);
    if (s) return s;
    try {
        s = arg.readUtf16String();
        if (s && s.length <= MAX_LEN) return s;
    } catch (_) {}
    try {
        s = arg.readCString();
        if (s && s.length <= MAX_LEN) return s;
    } catch (_) {}
    return null;
}

function hookIl2CppStringNew() {
    const names = [
        'il2cpp_string_new',
        'il2cpp_string_new_len',
        'il2cpp_string_new_utf16',
    ];
    let hooked = 0;
    names.forEach(function (name) {
        const addr = Module.findExportByName('libil2cpp.so', name);
        if (!addr) return;
        Interceptor.attach(addr, {
            onEnter(args) {
                this._name = name;
                if (name === 'il2cpp_string_new') {
                    this._cstr = args[0];
                } else if (name === 'il2cpp_string_new_len') {
                    this._cstr = args[0];
                } else if (name === 'il2cpp_string_new_utf16') {
                    this._utf16 = args[0];
                    this._len = args[1].toInt32();
                }
            },
            onLeave(retval) {
                let s = readIl2CppString(retval);
                if (!s && this._name === 'il2cpp_string_new' && this._cstr) {
                    try { s = this._cstr.readUtf8String(); } catch (_) {}
                }
                if (!s && this._name === 'il2cpp_string_new_utf16' && this._utf16 && this._len > 0) {
                    try { s = this._utf16.readUtf16String(this._len); } catch (_) {}
                }
                if (shouldCapture(s)) postCapture(s, this._name);
            }
        });
        hooked++;
        log('hooked ' + name);
    });
    return hooked;
}

function hookJavaTextView() {
    Java.perform(function () {
        try {
            const TextView = Java.use('android.widget.TextView');
            TextView.setText.overload('java.lang.CharSequence').implementation = function (cs) {
                try {
                    const s = cs ? cs.toString() : '';
                    if (shouldCapture(s)) postCapture(s, 'TextView.setText');
                } catch (_) {}
                return this.setText.overload('java.lang.CharSequence').call(this, cs);
            };
            log('hooked TextView.setText');
        } catch (e) {
            log('TextView hook skip: ' + e);
        }

        try {
            const TMP = Java.use('com.unity3d.textmeshpro.TMP_Text');
            /* 部分版本类名不同，失败可忽略 */
        } catch (_) {}

        try {
            const GetStringUTFChars = Module.findExportByName(null, 'GetStringUTFChars');
            if (GetStringUTFChars) {
                Interceptor.attach(GetStringUTFChars, {
                    onLeave(retval) {
                        if (retval.isNull()) return;
                        try {
                            const s = retval.readCString();
                            if (shouldCapture(s)) postCapture(s, 'JNI.UTF8');
                        } catch (_) {}
                    }
                });
                log('hooked GetStringUTFChars');
            }
        } catch (_) {}
    });
}

function hookIl2CppTextSetters() {
    const lib = Process.findModuleByName('libil2cpp.so');
    if (!lib) {
        log('libil2cpp.so not loaded');
        return 0;
    }
    log('libil2cpp.so @ ' + lib.base);
    let hooked = 0;
    const symbols = Module.enumerateSymbolsSync('libil2cpp.so');
    symbols.forEach(function (sym) {
        if (hooked >= 24) return;
        const n = sym.name || '';
        const lower = n.toLowerCase();
        if (
            (lower.indexOf('set_text') >= 0 || lower.indexOf('settext') >= 0) &&
            (lower.indexOf('text') >= 0 || lower.indexOf('tmp') >= 0)
        ) {
            try {
                Interceptor.attach(sym.address, {
                    onEnter(args) {
                        for (let i = 0; i < 4; i++) {
                            const s = tryReadStringArg(args[i]);
                            if (shouldCapture(s)) postCapture(s, 'il2cpp:' + n);
                        }
                    }
                });
                hooked++;
            } catch (_) {}
        }
    });
    log('il2cpp text setter hooks: ' + hooked);
    return hooked;
}

function bootstrap() {
    hookIl2CppStringNew();
    hookIl2CppTextSetters();
    if (Java.available) {
        Java.perform(function () {
            log('Java VM ready');
            hookJavaTextView();
        });
    }
}

setTimeout(bootstrap, 2500);

/* libil2cpp 晚加载时重试 */
let retries = 0;
const timer = setInterval(function () {
    retries++;
    if (Process.findModuleByName('libil2cpp.so')) {
        hookIl2CppStringNew();
        hookIl2CppTextSetters();
    }
    if (retries >= 8) clearInterval(timer);
}, 4000);
