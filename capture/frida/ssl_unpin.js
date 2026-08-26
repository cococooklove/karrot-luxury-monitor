/*
 * SSL cert pinning 우회 (Frida). 앱 트래픽이 mitmproxy 에 안 잡힐 때.
 *
 * 실행:
 *   frida -U -f <패키지명> -l capture/frida/ssl_unpin.js
 *   (이미 실행중이면)  frida -U <앱이름> -l capture/frida/ssl_unpin.js
 *
 * OkHttp/TrustManager/Conscrypt 계열 핀닝 대부분 무력화.
 * 커스텀 핀닝이면 콘솔 로그 보고 대상 클래스 추가.
 */
Java.perform(function () {
  // 1) TrustManager 교체 (표준 X509)
  try {
    var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
    var SSLContext = Java.use('javax.net.ssl.SSLContext');
    var TrustManager = Java.registerClass({
      name: 'com.karrot.TrustAll',
      implements: [X509TrustManager],
      methods: {
        checkClientTrusted: function () {},
        checkServerTrusted: function () {},
        getAcceptedIssuers: function () { return []; },
      },
    });
    var tms = [TrustManager.$new()];
    var init = SSLContext.init.overload(
      '[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;',
      'java.security.SecureRandom');
    init.implementation = function (km, tm, sr) { init.call(this, km, tms, sr); };
    console.log('[unpin] TrustManager replaced');
  } catch (e) { console.log('[unpin] TrustManager skip: ' + e); }

  // 2) OkHttp CertificatePinner 무력화
  try {
    var CP = Java.use('okhttp3.CertificatePinner');
    CP.check.overload('java.lang.String', 'java.util.List').implementation = function () {
      console.log('[unpin] okhttp CertificatePinner.check bypassed');
    };
  } catch (e) {}

  // 3) Conscrypt / TrustManagerImpl (Android 7+)
  try {
    var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
    TMI.checkTrustedRecursive.implementation = function () { return Java.use('java.util.ArrayList').$new(); };
    console.log('[unpin] Conscrypt TrustManagerImpl bypassed');
  } catch (e) {}

  console.log('[unpin] active');
});
