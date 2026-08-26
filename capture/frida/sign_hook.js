/*
 * 요청 서명 함수 후킹 + RPC 노출 (동적 서명 경로).
 * volatility 판정에서 헤더가 매번 바뀔 때 사용 = 앱 런타임이 요청마다 서명 생성.
 *
 * 2단계로 쓴다:
 *
 * [1] 서명 함수 찾기 (discovery)
 *   frida -U <앱> -l capture/frida/sign_hook.js
 *   콘솔에서:  discover("sign")   또는  discover("hmac") / discover("signature")
 *   → 이름에 키워드 들어간 메서드 목록 출력. 여기서 실제 서명 메서드 특정.
 *
 * [2] 특정 후 CONFIG 채우고 재실행 → rpc.exports.sign(payload) 로 서명 획득.
 *   Python: collector/karrot_api.py 가 frida.rpc 로 이 sign 을 호출.
 */

// [2]에서 채울 대상. discovery 로 찾은 값 기입.
var CONFIG = {
  className: '',      // 예: 'com.daangn.security.Signer'
  methodName: '',     // 예: 'sign'
  // 인자 형태: 'string' (payload 문자열 1개) 또는 'bytes'
  argType: 'string',
};

function discover(keyword) {
  keyword = (keyword || '').toLowerCase();
  Java.perform(function () {
    Java.enumerateLoadedClasses({
      onMatch: function (name) {
        if (name.toLowerCase().indexOf('daangn') < 0 &&
            name.toLowerCase().indexOf('karrot') < 0 &&
            name.toLowerCase().indexOf('towneers') < 0) return;
        try {
          var clazz = Java.use(name);
          var methods = clazz.class.getDeclaredMethods();
          for (var i = 0; i < methods.length; i++) {
            var m = methods[i].getName();
            if (m.toLowerCase().indexOf(keyword) >= 0) {
              console.log('[find] ' + name + ' . ' + m);
            }
          }
        } catch (e) {}
      },
      onComplete: function () { console.log('[find] done: ' + keyword); },
    });
  });
}

function hookSign() {
  if (!CONFIG.className || !CONFIG.methodName) {
    console.log('[sign] CONFIG 비었음. 먼저 discover("sign") 로 대상 특정.');
    return;
  }
  Java.perform(function () {
    var clazz = Java.use(CONFIG.className);
    var orig = clazz[CONFIG.methodName];
    // 관찰: 실제 호출 시 입력/출력 로깅
    orig.overloads.forEach(function (ov) {
      ov.implementation = function () {
        var ret = ov.apply(this, arguments);
        console.log('[sign] in=' + JSON.stringify([].slice.call(arguments)) +
                    ' out=' + ret);
        return ret;
      };
    });
    console.log('[sign] hooked ' + CONFIG.className + '.' + CONFIG.methodName);
  });
}

// Python(frida) 에서 script.exports.sign(payload) 로 호출
rpc.exports = {
  discover: discover,
  sign: function (payload) {
    var result = null;
    Java.perform(function () {
      var clazz = Java.use(CONFIG.className);
      var inst = clazz.$new ? clazz.$new() : clazz;  // 무인자 생성 가능 가정, 아니면 조정
      result = String(inst[CONFIG.methodName](payload));
    });
    return result;
  },
};

console.log('[sign_hook] loaded. use discover("sign") then set CONFIG.');
hookSign();
