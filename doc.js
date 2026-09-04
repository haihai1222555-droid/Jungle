// 문서 페이지는 대시보드에서 고른 밝기 설정을 그대로 따른다.
// 대시보드와 같은 열쇠(theme)를 읽으므로 오가며 색이 튀지 않는다.
(function () {
  try {
    var saved = localStorage.getItem('theme');
    if (saved === 'light') document.body.classList.add('light-theme');
  } catch (e) {
    // 브라우저가 저장소를 막아둔 경우 — 기본(어두운) 화면으로 둔다
  }
})();
