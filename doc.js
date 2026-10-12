// 문서 페이지는 대시보드에서 고른 밝기 설정을 그대로 따른다.
// 대시보드(app.js)와 같은 열쇠(jungle_theme)를 읽으므로 오가며 색이 튀지 않는다.
// 예전에는 'theme' 을 읽고 있었는데 대시보드는 그 이름으로 저장하지 않아서,
// 라이트로 바꿔 둔 사람도 문서 페이지는 늘 어둡게 열렸다.
(function () {
  try {
    var saved = localStorage.getItem('jungle_theme') || localStorage.getItem('theme');
    if (saved === 'light') document.body.classList.add('light-theme');
  } catch (e) {
    // 브라우저가 저장소를 막아둔 경우 — 기본(어두운) 화면으로 둔다
  }
})();
