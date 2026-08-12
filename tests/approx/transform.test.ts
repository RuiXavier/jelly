import vm from "vm";
import {approxTransform, PREFIX} from "../../src/approx/transform";

// Sentinel standing in for approx's `theProxy` (returned when a method call
// cannot proceed, so that approximate interpretation continues).
const PROXY: any = function proxy() {};

// Runs an instrumented CommonJS snippet in a fresh vm context. The _J$method
// stub mirrors the real approx hook (see approx.ts): it reads the property
// itself and suppresses read/lookup failures by returning the proxy, so the
// observable behavior — including tolerance of null-pointer method calls — is
// the same as during approximate interpretation. The snippet reports via
// module.exports.
function run(code: string): any {
    const res = approxTransform(code, "transform-test.js", "commonjs", () => {});
    expect(res).toBeDefined();
    const moduleObj: any = {exports: {}};
    const P = PREFIX;
    const sandbox: any = {module: moduleObj, require: () => ({}), console, Reflect};
    sandbox[P + "start"] = (_mod: string, m: any) => m || moduleObj;
    sandbox[P + "freeze"] = () => {};
    sandbox[P + "enter"] = () => {};
    sandbox[P + "this"] = () => {};
    sandbox[P + "init"] = () => {};
    sandbox[P + "catch"] = () => {};
    sandbox[P + "loop"] = () => {};
    sandbox[P + "alloc"] = (_mod: string, _loc: string, val: any) => val;
    sandbox[P + "comp"] = (_mod: string, _loc: string, val: any) => val;
    sandbox[P + "pw"] = (_mod: string, _loc: string, base: any, prop: any, val: any) => (base[prop] = val);
    sandbox[P + "dpr"] = (_mod: string, _loc: string, base: any, prop: any) => base[prop];
    sandbox[P + "method"] = (_mod: string, _loc: string, base: any, prop: any, _dyn: boolean, optMember: boolean, optCall: boolean, ...args: Array<any>) => {
        let fun;
        try {
            fun = optMember && (base === undefined || base === null) ? undefined : base[prop];
        } catch {
            return PROXY; // suppress read failure -> continue
        }
        if (optCall && (fun === undefined || fun === null))
            return undefined;
        if (typeof fun !== "function")
            return PROXY; // suppress "not a function" -> continue
        return Reflect.apply(fun, base, args);
    };
    sandbox[P + "fun"] = (_mod: string, _loc: string, fun: any, _opt: boolean, ...args: Array<any>) => Reflect.apply(fun, undefined, args);
    sandbox[P + "new"] = (_mod: string, _loc: string, fun: any, ...args: Array<any>) => Reflect.construct(fun, args);
    sandbox[P + "eval"] = (_mod: string, _loc: string, str: any) => str;
    sandbox[P + "require"] = (_mod: string, _loc: string, str: any) => str;
    vm.runInNewContext(res!.transformed, sandbox);
    return moduleObj.exports;
}

describe("approx transform method-call semantics", () => {

    // The defining property for approximate interpretation: a method call on a
    // null/undefined receiver must NOT throw, so force-execution continues.
    test("tolerates a method call on a null receiver and continues", () => {
        expect(run(`
            var reached = false;
            function f() {
                var x = null;
                x.foo();        // would throw without suppression
                reached = true; // only reached if the error was suppressed
            }
            f();
            module.exports = reached;
        `)).toBe(true);
    });

    // Likewise for a missing (non-function) property.
    test("tolerates calling a missing method and continues", () => {
        expect(run(`
            var reached = false;
            function f() {
                var x = {};
                x.nope();
                reached = true;
            }
            f();
            module.exports = reached;
        `)).toBe(true);
    });

    // Optional-chaining result semantics are still correct.
    test("base?.m() with null base yields undefined", () => {
        expect(run(`
            const x = null;
            module.exports = x?.m() === undefined;
        `)).toBe(true);
    });

    test("obj.m?.() with missing method yields undefined", () => {
        expect(run(`
            const x = {};
            module.exports = x.m?.() === undefined;
        `)).toBe(true);
    });

    // Ordinary method call works (no getter involved).
    test("ordinary method call evaluates the argument and calls the method", () => {
        expect(run(`
            var order = "";
            function mark(s) { order = order + s; return s; }
            const obj = { m(x) { mark("C"); return x; } };
            obj.m(mark("A"));
            module.exports = order;
        `)).toBe("AC");
    });

    // Documents the deliberate trade-off: because the property is read inside the
    // hook (to allow suppression), the method getter fires AFTER the arguments are
    // evaluated. Faithful JS order would be getter-then-argument; approximate
    // interpretation accepts argument-then-getter in exchange for tolerance.
    test("method getter is read after the arguments are evaluated", () => {
        expect(run(`
            var order = "";
            function mark(s) { order = order + s; return s; }
            const obj = { get m() { mark("G"); return function() { mark("C"); }; } };
            obj.m(mark("A"));
            module.exports = order;
        `)).toBe("AGC");
    });

    // The receiver expression is evaluated exactly once.
    test("receiver expression is evaluated once", () => {
        expect(run(`
            var order = "";
            function mark(s) { order = order + s; return s; }
            const holder = { obj: { m() { return 1; } } };
            function getObj() { mark("B"); return holder.obj; }
            getObj().m();
            module.exports = order;
        `)).toBe("B");
    });
});
