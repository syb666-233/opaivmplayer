/**
 * Frida 脚本原型：Hook Unity 文本组件（解密后在内存中设置 UI 文本时拦截）
 *
 * 前提：
 *   1. AIVM 虚拟机内已 root 或可注入 Frida
 *   2. adb connect 127.0.0.1:8555
 *   3. frida -U -f com.epidgames.trickcalrevive -l hook_unity_text.js --no-pause
 *
 * 说明：
 *   - 比 OCR 覆盖层准确率更高（直接读内存字符串）
 *   - 需根据 Il2CppDumper 导出的符号进一步精确化 RVA
 *   - 本脚本为探索性模板，需在真机/VM 运行时调试
 */

'use strict';

const PKG = 'com.epidgames.trickcalrevive';
const TRANSLATE_ENDPOINT = 'http://127.0.0.1:8787/translate'; // 本地翻译服务（可选）

function log(msg) {
    console.log('[trickcal-hook] ' + msg);
}

function hasHangul(s) {
    return /[\uAC00-\uD7AF]/.test(s);
}

function tryHookIl2CppStringSetters() {
    const lib = Process.findModuleByName('libil2cpp.so');
    if (!lib) {
        log('libil2cpp.so not loaded yet');
        return;
    }
    log('libil2cpp.so base=' + lib.base + ' size=' + lib.size);

    // 通用探索：扫描导出/符号中含 Text / TMP / SetText 的函数
    const symbols = Module.enumerateSymbolsSync('libil2cpp.so');
    let hooked = 0;
    symbols.forEach(sym => {
        const n = sym.name;
        if (!n) return;
        const lower = n.toLowerCase();
        if (
            (lower.indexOf('text') >= 0 && (lower.indexOf('set') >= 0 || lower.indexOf('text') >= 0)) ||
            lower.indexOf('tmp_text') >= 0 ||
            lower.indexOf('set_text') >= 0
        ) {
            if (hooked >= 20) return; // 限制 hook 数量，避免崩溃
            try {
                Interceptor.attach(sym.address, {
                    onEnter(args) {
                        // Il2CppString* 通常在 args[1] 或 args[2]，需运行时确认
                        for (let i = 0; i < 4; i++) {
                            try {
                                const p = args[i];
                                if (p.isNull()) continue;
                                const s = Memory.readUtf16String(p.add(0x14)); // Il2CppString 常见布局
                                if (s && hasHangul(s) && s.length >= 2 && s.length <= 200) {
                                    log('TEXT[' + n + '] arg' + i + ': ' + s);
                                }
                            } catch (_) {}
                        }
                    }
                });
                hooked++;
            } catch (e) {
                // ignore
            }
        }
    });
    log('hooked candidate symbols: ' + hooked);
}

function hookJNIGetString() {
    const env = Java.vm.getEnv();
    const getChars = Module.findExportByName(null, 'GetStringUTFChars');
    if (!getChars) return;
    Interceptor.attach(getChars, {
        onEnter(args) { this.jstr = args[1]; },
        onLeave(retval) {
            if (retval.isNull()) return;
            try {
                const s = retval.readCString();
                if (s && hasHangul(s) && s.length >= 2 && s.length <= 300) {
                    log('JNI UTF: ' + s);
                }
            } catch (_) {}
        }
    });
}

setTimeout(function () {
    if (Java.available) {
        Java.perform(function () {
            log('Java VM ready for ' + PKG);
            hookJNIGetString();
        });
    }
    tryHookIl2CppStringSetters();
}, 3000);
